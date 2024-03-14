FROM python:3.11

RUN apt-get update && \
apt-get install -y git build-essential cmake \
portaudio19-dev python3 python3-dev libhamlib-utils \
pipx && rm -rf /var/lib/apt/lists/*

WORKDIR /
RUN git clone https://github.com/drowe67/codec2.git
WORKDIR /codec2/build_linux
RUN cmake .. && make && make install && ldconfig


RUN pipx ensurepath

RUN pipx install poetry

WORKDIR /app

# install freeselcall
COPY . /app/
RUN chmod a+x /app/entrypoint.sh
RUN CFLAGS="-I/codec2/src" /root/.local/bin/poetry install -v

ENTRYPOINT [ "/bin/sh", "/app/entrypoint.sh" ]