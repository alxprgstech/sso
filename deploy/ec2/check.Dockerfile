FROM ubuntu:26.04@sha256:c098726dd9b9733f3e885f8de0ef375206a311b0a317eadc40d347b1115fb944
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    nginx openssl python3 python3-cryptography ca-certificates bash && rm -rf /var/lib/apt/lists/*
COPY deploy/ec2 /check/ec2
COPY scripts/check_ec2_nginx.py /check/check_ec2_nginx.py
CMD ["python3", "/check/check_ec2_nginx.py"]
