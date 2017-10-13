# NAME                  saltbot
# VERSION               0.1


FROM opensuse:tumbleweed
MAINTAINER Mihai Dinca: "mdinca@suse.com"

RUN zypper -n in git python-pip make
RUN git clone https://github.com/dincamihai/saltbot.git /saltbot
RUN pip install -e /saltbot

COPY prod_config.py /saltbot/config.py
COPY Makefile /root/Makefile

ENTRYPOINT ["make", "-f", "/root/Makefile", "-C", "/saltbot"]
CMD ["default"]
