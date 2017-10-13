#!/usr/bin/env python

import os
import uuid
import argparse
import requests
import StringIO
from jinja2 import Environment, PackageLoader
from requests.auth import HTTPBasicAuth
from requests import Request
from saltbot_check import check_building
import config


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


def update_service(auth, project, package, gitbranch):
    # generate _service file content
    # upload it to branched project
    env = Environment(loader=PackageLoader('saltbot', 'templates'))
    template = env.get_template('_service')
    _service = template.render(branch=gitbranch)
    response = requests.put(
        'https://api.opensuse.org/source/{project}/{package}/_service'.format(project=project, package=package),
        data=_service,
        auth=auth
    )
    response.raise_for_status()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', required=True, dest='project', type=str)
    parser.add_argument('--gitbranch', required=True, dest='gitbranch', type=str)
    args = parser.parse_args()
    auth = HTTPBasicAuth(config.user, config.password)
    branched_project = branch_package(auth, args.project, 'salt')
    update_service(auth, branched_project, 'salt', args.gitbranch)
    response = check_building(auth, config.token, branched_project)
    if not response:
        exit(1)
    exit(0)


if __name__ == '__main__':
    main()
