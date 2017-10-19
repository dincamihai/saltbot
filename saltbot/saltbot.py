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
from bs4 import BeautifulSoup
import config


def check_building(auth, token, project):
    not_done = True
    retries = 3
    session = requests.Session()
    request = Request(
        'GET',
        'https://api.opensuse.org/build/{project}/_result'.format(project=project),
        auth=auth
    )
    prepped = request.prepare()
    while not_done:
        response = session.send(prepped)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        print soup
        results = soup.findAll('result')
        if (
            any(map(lambda it: it.get('dirty') == 'true', results)) or
            any(map(lambda it: it.get('code') == 'unknown', results))
        ):
            time.sleep(120)
            continue
        statuses = [it.get('code') for it in soup.findAll('status')]
        if 'broken' in statuses and retries > 0:
            response = requests.post(
                'https://api.opensuse.org/trigger/runservice',
                headers={'Authorization': 'Token {token}'.format(token=token)},
                data={'project': project, 'package': 'salt'},
            )
            retries -= 1
        elif retries <= 0:
            break
        elif 'failed' in statuses:
            break
        elif all(map(lambda it: it == 'succeeded', statuses)):
            return True
        time.sleep(120)
    return False


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
    if os.path.isfile('cache/events.etag'):
        with open('cache/events.etag', 'rb') as events_etag:
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
    with open('cache/events.etag', 'wb') as events_etag:
        events_etag.write(response.headers.get('etag'))
    return response


@authenticate('git')
def fetch_prs(auth, owner, repo, branch):
    response = fetch_events(owner, repo)
    new_events = []
    cached_events = []

    if os.path.isfile('cache/events.response'):
        with open('cache/events.response', 'rb') as events_response:
            cached_events = json.load(events_response)

    if not response.status_code == 304:
        new_events = response.json()

    def event_filter(event):
        return (
            event['type'] == 'PullRequestEvent' and
            event['payload']['pull_request']['state'] == 'open' and
            event['payload']['pull_request']['base']['ref'] == branch
        )

    filtered_new_events = filter(event_filter, new_events)

    events = cached_events + filtered_new_events

    with open('cache/events.response', 'wb') as events_response:
        json.dump(events, events_response, indent=4)


def pop_event(owner, repo, branch):

    fetch_prs(owner, repo, branch)

    event = None

    with open('cache/events.response', 'rb') as events_response:
        events = json.load(events_response)

    if events:
        event = events.pop()

    with open('cache/events.response', 'wb') as events_response:
        json.dump(events, events_response, indent=4)

    return event


def poll_pr(owner, repo, branch, job):
    while True:
        event = pop_event(owner, repo, branch)
        if not event:
            break
        print("Processing Event: {id}".format(id=event['id']))
        trigger_jenkins(job, event['payload']['pull_request'])
        time.sleep(5)
    exit(0)


@authenticate('jenkins')
def trigger_jenkins(auth, job, pr):
    print("Trigger for PR: {url}".format(url=pr['url']))
    url = "https://ci.suse.de/crumbIssuer/api/json"
    crumb_response = requests.get(url, verify=False, auth=auth)
    crumb_response.raise_for_status()
    response = requests.post(
        "https://ci.suse.de/job/{name}/build?delay=0sec".format(
            name=job
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

    subparsers = parser.add_subparsers()

    parser_poll = subparsers.add_parser('poll')
    parser_build = subparsers.add_parser('build')

    parser_poll.add_argument('--action', dest='action', type=str, default='poll')
    parser_poll.add_argument('--owner', required=True, dest='owner', type=str)
    parser_poll.add_argument('--repo', required=True, dest='repo', type=str)
    parser_poll.add_argument('--branch', required=True, dest='branch', type=str, default='master')
    parser_poll.add_argument('--job', required=True, dest='job', type=str)

    parser_build.add_argument('--action', dest='action', type=str, default='build')
    parser_build.add_argument('--project', required=True, dest='project', type=str)
    parser_build.add_argument('--gitbranch', required=True, dest='gitbranch', type=str)

    args = parser.parse_args()

    if args.action == 'poll':
        poll_pr(args.owner, args.repo, args.branch, args.job)
    elif args.action == 'build':
        branched_project = branch_package(args.project, 'salt')
        update_service(branched_project, 'salt', args.gitbranch)
        response = check_building(config.obs['token'], branched_project)

    if not response:
        exit(1)
    exit(0)


if __name__ == '__main__':
    main()
