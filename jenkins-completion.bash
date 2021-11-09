#!/usr/bin/env bash
# Provide bash completions for job names on the (configured) Jenkins server
# Source this script from your .bashrc or copy it into /etc/bash_completion.d/

_jenkins()
{
    local cur prev opts
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    # only include most commonly used options in completion
    opts_short="-b -p -B -c -w -i -a -v -o -d"
    opts_long="--groovy --get-groovy --get-config ---post-config --arti --list --que --nodes --makeconf"

    COMPREPLY=()

    if [[ ${cur} == -* ]] ; then
        # if only one dash, expand all options
        COMPREPLY=( $(compgen -W "${opts_short} ${opts_long}" -- ${cur}) )
        return 0
    elif [[ ${cur} == --* ]] ; then
        # if two dashes, expand only long options
        COMPREPLY=( $(compgen -W "${opts_long}" -- ${cur}) )
        return 0
    else
        # else expand jobs
        jobs=$(jenkins --list 2>/dev/null)
        COMPREPLY=($(compgen -W "${jobs}" -- "${cur}"))
        return 0
    fi
}
complete -F _jenkins jenkins
complete -F _jenkins jenkins.py
