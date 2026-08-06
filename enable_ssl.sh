#!/usr/bin/env bash
echo "=== Triggering Certbot SSL Certificate Generation on EC2 ==="
ssh -o StrictHostKeyChecking=no -i ~/Downloads/pitchdock-key.pem ubuntu@13.63.174.222 'sudo certbot --nginx -d pitchdock.xyz -d www.pitchdock.xyz --non-interactive --agree-tos -m ss2341@srmist.edu.in'
