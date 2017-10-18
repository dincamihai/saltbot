#!/usr/bin/env python

import os
import time
import json
import uuid
import argparse
import requests
import StringIO
from functools import wraps
from jinja2 import Environment, PackageLoader
from requests.auth import HTTPBasicAuth
from requests import Request
from saltbot_check import check_building
import config


def get_auth(service):
    auth = None
    if service == 'obs':
        auth = HTTPBasicAuth(config.obs['user'], config.obs['password'])
    elif service == 'git':
        auth = HTTPBasicAuth(config.github['user'], config.github['token'])
    elif service == 'jenkins':
        auth = HTTPBasicAuth(config.jenkins['user'], config.jenkins['password'])
    return auth


def authenticate(service):

    def decorator(fun):
        @wraps(fun)
        def wrapper(*args, **kwargs):
            return fun(get_auth(service), *args, **kwargs)
        return wrapper

    return decorator


@authenticate('obs')
def branch_package(auth, project, package):
    # branch project
    ident = uuid.uuid1()
    branched_project = '{project}-{ident}'.format(project=project, ident=ident.hex)
    response = requests.post(
        'https://api.opensuse.org/source/{project}/{package}?cmd=branch'.format(project=project, package=package),
        data={'target_project': branched_project},
        auth=auth
    )
    response.raise_for_status()
    return branched_project


def render_service(gitbranch):
    # generate _service file content
    env = Environment(loader=PackageLoader('saltbot', 'templates'))
    template = env.get_template('_service')
    return template.render(branch=gitbranch)


@authenticate('obs')
def update_service(auth, project, package, gitbranch):
    # upload it to branched project
    _service = render_service(gitbranch)
    response = requests.put(
        'https://api.opensuse.org/source/{project}/{package}/_service'.format(project=project, package=package),
        data=_service,
        auth=auth
    )
    response.raise_for_status()


@authenticate('git')
def fetch_events(auth, owner, repo):
    etag = None
    if os.path.isfile('events.tag'):
        with open('events.etag', 'rb') as events_etag:
            etag = events_etag.read().strip()
    headers = dict()
    if etag:
        headers['If-None-Match'] = etag
    response = requests.get(
        'https://api.github.com/repos/{owner}/{repo}/events'.format(
            owner=owner, repo=repo),
        headers={'If-None-Match':  etag},
        auth=auth
    )
    response.raise_for_status()
    with open('events.etag', 'wb') as events_etag:
        events_etag.write(response.headers.get('etag'))
    return response


@authenticate('git')
def fetch_prs(auth, owner, repo):
    response = fetch_events(owner, repo)
    new_events = []
    cached_events = []

    if os.path.isfile('events.response'):
        with open('events.response', 'rb') as events_response:
            cached_events = json.load(events_response)

    if not response.status_code == 304:
        new_events = response.json()
    events = cached_events + new_events

    with open('events.response', 'wb') as events_response:
        json.dump(events, events_response, indent=4)


def pop_event(owner, repo):

    fetch_prs(owner, repo)

    event = None

    with open('events.response', 'rb') as events_response:
        events = json.load(events_response)

    if events:
        event = events.pop()

    with open('events.response', 'wb') as events_response:
        json.dump(events, events_response, indent=4)

    return event


def trigger_on_pr(owner, repo):
    event = True
    while event:
        event = pop_event(owner, repo)
        if not event:
            continue
        print("Processing Event:")
        print(event)
        if event['type'] == 'PullRequestEvent' and event['payload']['pull_request']['state'] == 'open':
            # statuses = requests.get(
            #     event['payload']['pull_request']['_links']['statuses']['href'],
            #     auth=auth
            # )
            # if 'pending' in  statuses.json():
            #     continue
            trigger_jenkins_job(event['payload']['pull_request'])
            time.sleep(5)
        else:
            continue
    exit(1)


@authenticate('jenkins')
def trigger_jenkins_job(auth, pr):
    url = "https://ci.suse.de/crumbIssuer/api/json"
    crumb_response = requests.get(url, verify=False, auth=auth)
    crumb_response.raise_for_status()
    response = requests.post(
        "https://ci.suse.de/job/{name}/build?delay=0sec".format(
            name='salt-obs-build'
        ),
        data={
            "json": json.dumps({
                "parameter": [{
                    "name": "branch",
                    "value": pr['head']['ref']
                }]
            })
        },
        headers={
            "Jenkins-Crumb": crumb_response.json()['crumb'],
            "Content-Length": "0"
        },
        verify=False,
        auth=auth
    )
    response.raise_for_status()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', required=True, dest='project', type=str)
    parser.add_argument('--gitbranch', required=True, dest='gitbranch', type=str)
    args = parser.parse_args()
    branched_project = branch_package(args.project, 'salt')
    update_service(branched_project, 'salt', args.gitbranch)
    response = check_building(config.obs['token'], branched_project)
    if not response:
        exit(1)
    exit(0)


if __name__ == '__main__':
    main()
