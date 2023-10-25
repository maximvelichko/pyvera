#!/usr/bin/env bash
set -euf -o pipefail

SELF_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$SELF_DIR/.."

source "$SELF_DIR/common.sh"

assertPython


echo
echo "===Settting up venv==="
enterVenv


echo
echo "===Installing poetry==="
pip install poetry


echo
echo "===Installing dependencies==="
poetry install

echo
echo "===Sorting imports==="
ISORT_ARGS="--apply"
if [[ "${CI:-}" = "1" ]]; then
  ISORT_ARGS="--check-only"
fi

isort $ISORT_ARGS


echo
echo "===Formatting code==="
if [[ `which black` ]]; then
  BLACK_ARGS=""
  if [[ "${CI:-}" = "1" ]]; then
    BLACK_ARGS="--check"
  fi

  black $BLACK_ARGS .
else
  echo "Warning: Skipping code formatting. You should use python >= 3.6."
fi


echo
echo "===Lint with flake8==="
flake8

# Needs work to run cleanly with python 3.9
# echo
# echo "===Lint with mypy==="
# mypy .


echo
echo "===Lint with pylint==="
set +e +o pipefail
pylint $LINT_PATHS
pylint_exitcode=$?
set -e -o pipefail

if (( (pylint_exitcode & 0x1) != 0 )); then
    echo "=> Fatal"
fi
if (( (pylint_exitcode & 0x2) != 0 )); then
    echo "=> Error"
fi
if (( (pylint_exitcode & 0x4) != 0 )); then
    echo "=> Warning"
fi
if (( (pylint_exitcode & 0x8) != 0 )); then
    echo "=> Refactor"
fi
if (( (pylint_exitcode & 0x10) != 0 )); then
    echo "=> Convention"
fi
if (( (pylint_exitcode & 0x20) != 0 )); then
    echo "=> Usage"
fi
if (( (pylint_exitcode & 0x23) != 0 )); then
    echo "=> Fatal, Errors or Usage"
    exit 1
fi


echo
echo "===Test with pytest==="
pytest


echo
echo "===Building package==="
poetry build

echo
echo "===Uploading code coverage==="
if [[ "${CI:-}" = "1" ]] && [[ -n "${CODECOV_TOKEN:-}" ]]; then
  curl -s https://codecov.io/bash | bash
else
  echo "Skipping. Will only run during continuous integration build."
fi


echo
echo "Build complete"
