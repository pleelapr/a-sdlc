#!/bin/sh
# docker/minio/init.sh — Create the default bucket in MinIO on first start.
#
# This script runs as a one-shot init container (minio-init) after MinIO
# reports healthy.  It is idempotent: re-running it when the bucket already
# exists is a no-op.
#
# Required environment variables (set via docker-compose.yml):
#   MINIO_ROOT_USER     — MinIO admin username
#   MINIO_ROOT_PASSWORD — MinIO admin password
#   MINIO_BUCKET        — Bucket name to create (default: asdlc-content)

set -eu

BUCKET="${MINIO_BUCKET:-asdlc-content}"

echo "Configuring MinIO client alias..."
mc alias set myminio http://minio:9000 "${MINIO_ROOT_USER}" "${MINIO_ROOT_PASSWORD}"

if mc ls "myminio/${BUCKET}" > /dev/null 2>&1; then
    echo "Bucket '${BUCKET}' already exists — skipping creation."
else
    echo "Creating bucket '${BUCKET}'..."
    mc mb "myminio/${BUCKET}"
    echo "Bucket '${BUCKET}' created successfully."
fi

echo "MinIO initialization complete."
