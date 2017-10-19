# NAME                  saltbot
# VERSION               0.1


FROM opensuse:tumbleweed
MAINTAINER Mihai Dinca: "mdinca@suse.com"

RUN zypper -n in git python-pip make

COPY Makefile /root/Makefile

ENTRYPOINT ["saltbot.py"]

ARG NOCACHE=nocache
RUN git clone https://github.com/dincamihai/saltbot.git /saltbot
COPY prod_config.py /saltbot/config.py
RUN pip install -e /saltbot
RUN mkdir /saltbot/cache
