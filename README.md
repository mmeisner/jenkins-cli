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
usage: jenkins [-b] [-p PARAMS] [-B] [-c] [-w] [-t TIMEOUT] [--groovy FILE] [--get-groovy]
               [--get-config] [--post-config FILE] [-i] [-a] [--arti] [--ws PATH] [-o DIR]
               [--wipews] [--list] [--que] [--nodes] [-d srhtj] [--no-progress] [--url URL]
               [--auth NAME_TOK] [--makeconf] [-v] [-h]
               [JOB[/ID]]

Start Jenkins jobs remotely via Jenkins REST API, show console log,
replace pipeline script, list nodes or job queue, print job build info,
retrieve build artifacts, and much much more

Configuration is read from $HOME/.jenkins.ini

Position arguments:
  JOB[/ID]            Jenkins job name (and build ID). This is a mandatory argument for many
                      commands

Build arguments:
  -b                  Start build job
  -p PARAMS           Job params given as comma separated list of key=value pairs, e.g.
                      'foo=1,baz=10'
  -B                  Stop build job. Give option twice to cancel job
  -c                  Get console ouput for job
  -w                  Wait for job completion. Useful when job is already running
  -t TIMEOUT          Build completion timeout (when -b option is given). Default is auto-computed

Project/job config and groovy commands/actions:
  --groovy FILE       Get config.xml, replace groovy script with FILE and post new config
  --get-groovy        Get config.xml, extract groovy script and print it
  --get-config        Get config.xml and print it
  --post-config FILE  Read FILE and post as config.xml to Jenkins job JOBNAME

Project/job commands/actions:
  -i                  Get project summary info
  -a                  List all builds of project
  --arti              Get artifacts from build and save them
  --ws PATH           Get file PATH from workspace. Use 'some/sub/dir/zip' to get zip of directory
  -o DIR              Output directory for fetched files (e.g. from --arti or --ws command
                      options)
  --wipews            Wipe out (delete) workspace of JOB_NAME

Jenkins list actions:
  --list              List all projects
  --que               List Jenkins queue
  --nodes             List Jenkins build nodes/machines

Misc options:
  -d srhtj            Log HTTP transactions: s = send, r = response status, h = response headers,
                      t = response text, j = response pretty json
  --no-progress       Suppress wait progress messages
  --url URL           Jenkins server URL. Default is https://jenkins.url.not.set or JENKINS_URL
                      from environment
  --auth NAME_TOK     Username and API token, separated by colon. Usually required for --get-
                      config, --post-config
  --makeconf          Write a configuration file template
  -v                  Be more verbose
  -h                  Show usage. Give option twice to see usage examples

See command-line examples with: jenkins -hh
```

TODO: One oddity of note is that Jenkins API documentation and API calls are
using "*job*", "*project*" and "*build*"

## Similar Work

  * [jenkins-cli](https://github.com/jenkins-zh/jenkins-cli)
  * [jenni: Jenkins Personal Assistant](https://github.com/m-sureshraj/jenni)
