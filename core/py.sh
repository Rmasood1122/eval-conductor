#!/bin/sh
# Run a plugin tool under the first interpreter that really is Python 3.10+.
#
#   sh py.sh TOOL.py [ARGS...]
#
# Every command line goes through this instead of a bare `python3`. Finding a
# name on PATH proves nothing: on Windows, `python3` is often the Microsoft Store
# alias stub, which `command -v` finds and which then exits 9009 (49 as a byte)
# instead of running Python. So each candidate is probed by running it.
#
# The winner is exported as EVAL_CONDUCTOR_PY so a tool can print copy-pasteable
# next steps that name the interpreter that actually ran.
for py in python3 python "py -3"; do
  # $py is unquoted on purpose: "py -3" must split into a command and a flag.
  if $py -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >/dev/null 2>&1; then
    EVAL_CONDUCTOR_PY=$py
    export EVAL_CONDUCTOR_PY
    exec $py "$@"
  fi
done
echo "eval-conductor: no working Python 3.10+ found (tried python3, python, py -3). Install Python 3.10+ and make sure one of those runs it. On Windows, a python3 that points you to the Microsoft Store is an alias stub, not Python." >&2
exit 127
