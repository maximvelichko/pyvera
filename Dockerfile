FROM python:3.5

VOLUME /repo

RUN pip install \
  requests \
  pylint

WORKDIR /repo
