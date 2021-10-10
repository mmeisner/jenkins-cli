#!/usr/bin/env bash
# Provide bash completions for job names on the (configured) Jenkins server
# Source this script from your .bashrc or copy it into /etc/bash_completion.d/

_jenkins_completions()
{
    [ "${#COMP_WORDS[@]}" == "2" ] || return

    jobs=$(jenkins --list 2>/dev/null)
    COMPREPLY=($(compgen -W "${jobs}" "${COMP_WORDS[1]}"))
}
complete -F _jenkins_completions jenkins
complete -F _jenkins_completions jenkins.py
