#!/usr/bin/env python3
# Run Jenkins job, retrieve build artifacts and save them to local file system

__author__ = "Mads Meisner-Jensen"
import os
import sys
import argparse
import time
import json
import requests
from pathlib import Path
from pprint import pprint, pformat


#####################################################################
# Jenkins
#####################################################################

class Jenkins(object):
    def __init__(self, verbose=1):
        # disable InsecureRequestWarning: "Unverified HTTPS request" warnings
        requests.packages.urllib3.disable_warnings(requests.urllib3.exceptions.InsecureRequestWarning)

        self.server_url = "https://jenkins.lan"
        self._conn_ok = False
        self._verify = False
        self.assert_connectivity()

        self.job_url = None
        self.artifacts = None

        self.verbose = verbose
        # Allow "remote build launch" of Jenkins jobs. Configured in actual Jenkins job.
        self.default_build_params = { 'token': "build" }


    def assert_connectivity(self):
        # NOTE: we could also use requests.get(..., cert=FILEPATH) to pass in the CA certificate

        print(f"Checking Jenkins connectivity: {self.server_url}")
        try:
            requests.get(self.server_url, verify=False)
            self._conn_ok = True
        except requests.exceptions.SSLError:
            error_msg_cacert = """
It seems you don't have the Jenkins (self-signed) CA certificate installed
or the certificate has expired. 
"""
            raise RuntimeError(error_msg_cacert)


    def print(self, s, level=1):
        if self.verbose >= level:
            print(s)

    def get_last_successful_artifact(self, name=None):
        """

        :param name: Jenkins job name
        :return: url_artifacts, list of dictionaries:
            [{'displayPath': 'foo.zip', 'fileName': 'foo.zip', 'relativePath': 'foo.zip'}],
        """
        url_lastsuccess = f"{self.server_url}/job/{name}/lastSuccessfulBuild"
        url = f"{url_lastsuccess}/api/json"
        try:
            r = requests.get(url, verify=self._verify)
            response = json.loads(r.text)
            self.job_url = url_lastsuccess
            self.artifacts = response.get('artifacts', [])
            self.print(f"Sent    : {r.url}")
            self.print(f"Received: {r.text}")
            return url_lastsuccess, self.artifacts
        except:
            print(f"FAILED: GET {r.url}")
            raise


    def req_wait(self, url, key, wait_msg="result", timeout=60, poll_interval=2):
        if not poll_interval:
            poll_interval = max(int(timeout / 30), 5)

        started = time.time()
        for i in range(0, int(timeout / poll_interval)):
            time.sleep(poll_interval)
            elapsed = time.time() - started
            if elapsed < 20 or int(elapsed) % 5 < poll_interval:
                print(f"Waiting for {wait_msg}: {elapsed:.0f}s of {timeout}s")

            r = requests.get(url, verify=self._verify)
            response = json.loads(r.text)
            # only return if key exists AND has a value
            if response.get(key) is not None:
                self.print(f"Received: {r.text}")
                return response

        print(f"Received: {r.text}")
        msg = f"TIMEOUT after {elapsed:.0f}s while waiting for {wait_msg}"
        raise RuntimeError(msg)

    def run_job(self, name=None, url_loc=None, params=None, build_wait=60):
        """

        :param name:    Jenkins job name
        :param url_loc: "build" or "buildWithParameters"
        :param params:  Dictionary of build parameters
        :param build_wait: Seconds to wait for build completion
        :return:job_url, artifacts dict
        """

        job_url = f"{self.server_url}/job/{name}"
        url_startjob = f"{job_url}/{url_loc}"
        started = time.time()

        print(f"Requesting start of Jenkins job {name}")
        if not params:
            params = {}
        params.update(self.default_build_params)

        try:
            # url = requests.Request("GET", url_startjob, params=params).prepare().url
            req = requests.get(url_startjob, params=params, verify=self._verify)
            self.print(f"Sent    : {req.url}")
            self.print(f"Received: {req.headers}")
        except Exception:
            raise RuntimeError(f"FAILED to start jenkins job {name} with {req.url}")

        if 'Location' not in req.headers:
            print(f"Received: {req.headers}")
            raise RuntimeError("Location header not found in response. Is URL correct?")
        location_url = req.headers['Location']

        print(f"Requested Jenkins job {name}, waiting for build number")

        url = f"{location_url}api/json"
        response = self.req_wait(url, key="executable", wait_msg="job start", timeout=60)
        number = response['executable']['number']

        print(f"Started Jenkins job {name}, build number {number}")

        url = f"{job_url}/{number}/api/json"
        response = self.req_wait(url, key="result", wait_msg="job completion", timeout=build_wait)
        if response['result'] != 'SUCCESS':
            print(f"Received: {response}")
            raise RuntimeError(f"Jenkins job result='{response['result']}' but expected SUCCESS")

        artifacts = response['artifacts']
        if not artifacts:
            print(f"Received: {response}")
            raise RuntimeError("No Jenkins build artifacts found!?")

        elapsed = time.time() - started
        print(f"Build completed in {elapsed:.0f}s")

        self.job_url = job_url
        self.artifacts = artifacts
        return job_url, artifacts


    def fetch_artifacts(self, dest_dir, artifacts=None, url=None):
        if not url:
            url = self.job_url
        if not artifacts:
            artifacts = self.artifacts

        for item in artifacts:
            relpath = item['relativePath']
            artifact_url = f"{url}/artifact/{relpath}"
            req = requests.get(artifact_url, verify=self._verify)

            dest_path = Path(dest_dir, item['fileName'])
            print(f"Saving artifact {dest_path}")
            with dest_path.open('wb') as f:
                f.write(req.content)


def parser_create():
    description = "Run Jenkins job, retrieve build artifacts and save them to local file system"
    prog = os.path.basename(__file__)
    examples = f"""
Examples:
  {prog} sandbox
  {prog} house doors=2,windows=8 -o /tmp
"""
    parser = argparse.ArgumentParser(
        description=description, epilog=examples, add_help=False, formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument(dest='jobname', metavar='JOBNAME', type=str,
        help="Jenkins job name")
    parser.add_argument('-o', dest='outdir', metavar='DIR', default=".",
        help="Output directory for build artifacts")
    parser.add_argument('-t', dest='timeout', type=int, default=120,
        help="Jenkins build timeout. Default is 120s")
    parser.add_argument(nargs='?', dest='params', metavar='PARAMS', type=str,
        help="Job params given as comma separated list of key=value pairs, e.g. 'foo=1,baz=10'")
    parser.add_argument('-a', dest='only_artifacts', default=False, action="store_true",
        help="Do not start a job, just get the artifacts from last successfull build")
    parser.add_argument('-v', dest='verbose', action='count', default=0,
        help='Be more verbose')
    parser.add_argument('-h', action='help',
        help='Show this help message and exit')
    return parser

if __name__ == "__main__":
    parser = parser_create()
    opt = parser.parse_args()

    params = None
    if opt.params:
        try:
            kv_list = opt.params.split(",")
            params = { }
            for kv in kv_list:
                k, v = kv.split("=")
                params[k] = v
        except:
            raise ValueError("Invalid job PARAMS list")

    url_loc = "buildWithParameters" if params else "build"

    jenkins = Jenkins(verbose=opt.verbose)
    if opt.only_artifacts:
        jenkins.get_last_successful_artifact(name=opt.jobname)
    else:
        jenkins.run_job(name=opt.jobname, url_loc=url_loc, params=params, build_wait=opt.timeout)

    jenkins.fetch_artifacts(opt.outdir)

    print("ok")
