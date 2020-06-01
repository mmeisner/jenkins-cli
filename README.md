# Jenkins Command-line to Start Build Jobs

`jenkins.py` is a single-file python3 script with no dependencies except
the Python3 standard library.

I made it because I got tired of the Jenkins web UI that can be very
tedious when you are trying to make your Groovy script for some build job.
Plus, the Groovy script editor in the web UI sucks.

It can:
  - Upload Groovy script for a pipeline build job
  - Start build job (normal or parameterized)
    - Optionally displaying build console output on your screen
  - Stop build job
  - Wait for some job to complete
  - Download build artifacts
  - List status and overview of any build project/job
  - Be configured with a simple `jenkins.ini` file (there isn't much)
  - List all build jobs
  - List the build job queue
  - List all build nodes/machines
  - Get and save the job configuration (as `config.xml`)
  - Post/replace the job configuration (from local `config.xml` file)

My use case was served by this command-line:

```bash
jenkins.py --groovy build.groovy -bc MyProject
```
This will upload the groovy script of *MyProject* with `build.groovy`. Then
start a build (`-b`) while showing console output (`-c`)


This is the usage for `jenkins.py`:
```
$ ./jenkins.py -h
usage: jenkins.py [-p PARAMS] [-b] [-B] [-c] [-a] [-o DIR] [-i] [-w]
                  [-t TIMEOUT] [--arti] [--groovy FILE] [--get-config FILE]
                  [--post-config FILE] [--auth NAME_TOK] [--list] [--que]
                  [--nodes] [--ws PATH] [--url URL] [--wipews] [--no-progress]
                  [-d srhtj] [-v] [-h]
                  [JOB[/ID]]

Start Jenkins jobs remotely via Jenkins REST API, retrieve build artifacts,
and much more

Configuration is read from $HOME/.jenkins.ini

positional arguments:
  JOB[/ID]            Jenkins job name (and build ID)

optional arguments:
  -p PARAMS           Job params given as comma separated list of key=value
                      pairs, e.g. 'foo=1,baz=10'
  -b                  Start build job
  -B                  Stop build job. Give option twice to cancel job
  -c                  Get console ouput for job
  -a                  Get all (e.g. get all build of project)
  -o DIR              Output directory for build artifacts
  -i                  Get info for project
  -w                  Wait for job completion. Useful when job is already
                      running
  -t TIMEOUT          Build completion timeout (when -b option is given).
                      Default is auto-computed
  --arti              Get artifacts from build and save them
  --groovy FILE       Get config.xml, replace groovy script with FILE and post
                      new config
  --get-config FILE   Get config.xml and save to FILE
  --post-config FILE  Read FILE and post as config.xml to Jenkins job JOBNAME
  --auth NAME_TOK     Username and API token, separated by colon. Usually
                      required for --get-config, --post-config
  --list              List all projects
  --que               List Jenkins queue
  --nodes             List Jenkins build nodes/machines
  --ws PATH           Get file PATH from workspace
  --url URL           Jenkins server URL. Default is
                      https://jenkins.url.not.set or JENKINS_URL from
                      environment
  --wipews            Wipe out (delete) workspace of JOB_NAME
  --no-progress       Suppress wait progress messages
  -d srhtj            Log HTTP transactions: s = send, r = response status, h
                      = response headers, t = response text, j = response
                      pretty json
  -v                  Be more verbose
  -h                  Show usage. Give option twice to see usage examples

See command-line examples with: jenkins.py -hh
```

TODO: One oddity of note is that Jenkins API documentation and API calls are
using "*job*", "*project*" and "*build*"

## Similar Work

  * [jenkins-cli](https://github.com/jenkins-zh/jenkins-cli)
  * [jenni: Jenkins Personal Assistant](https://github.com/m-sureshraj/jenni)
