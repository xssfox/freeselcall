FROM python:3.11 as builder

RUN apt-get update && \
apt-get install -y git build-essential cmake \
portaudio19-dev python3 python3-dev && rm -rf /var/lib/apt/lists/*


WORKDIR /app

# install freeselcall
COPY . /app/

RUN pip install poetry && python -m poetry build -v

FROM python:3.11

RUN apt-get update && \
apt-get install -y portaudio19-dev python3-dev \
&& pip install pyaudio \
&& apt-get remove -y portaudio19-dev python3-dev && \
rm -rf /var/lib/apt/lists/*


COPY --from=builder /app/dist/*.whl /app/

RUN pip install /app/*.whl

COPY ./entrypoint.sh /app/entrypoint.sh

RUN chmod a+x /app/entrypoint.sh
ENTRYPOINT [ "/bin/sh", "/app/entrypoint.sh" ]