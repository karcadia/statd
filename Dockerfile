FROM alpine

RUN apk add uv

COPY all.env /app/
COPY app.py /app/
COPY pyproject.toml /app/

WORKDIR /app
RUN uv sync

# Create a non-root account and switch to it.
RUN adduser -Du 1111 statd && chown 1111:1111 /app -R
USER 1111

# Expose relevant ports.
EXPOSE 5000

ENTRYPOINT /bin/sh -c 'source /app/all.env && cd /app && uv run app.py'
