FROM python:3.11-alpine as builder

RUN apk add --no-cache gcc cmake musl-dev portaudio-dev libffi-dev make


WORKDIR /app

# install freeselcall
COPY . /app/

RUN pip install poetry && python -m poetry build -v

FROM python:3.11-alpine

RUN apk add --no-cache portaudio gcc musl-dev portaudio-dev libffi-dev\
&& pip install --no-cache-dir pyaudio cffi \
&& apk del gcc musl-dev portaudio-dev libffi-dev


COPY --from=builder /app/dist/*.whl /app/

RUN pip install --no-cache-dir /app/*.whl

COPY ./entrypoint.sh /app/entrypoint.sh

RUN chmod a+x /app/entrypoint.sh
ENTRYPOINT [ "/bin/sh", "/app/entrypoint.sh" ]