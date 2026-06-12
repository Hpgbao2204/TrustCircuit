FROM amazonlinux:2023

RUN dnf install -y python3 python3-pip python3-setuptools && \
    python3 -m pip install --no-cache-dir aws-nsm-interface && \
    dnf clean all

COPY enclave_worker.py /app/enclave_worker.py

CMD ["python3", "/app/enclave_worker.py"]
