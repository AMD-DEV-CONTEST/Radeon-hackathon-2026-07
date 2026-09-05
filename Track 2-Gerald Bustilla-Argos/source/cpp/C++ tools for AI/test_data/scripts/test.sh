#!/bin/bash
set -e
echo "Running tests..."
./build/aisearch test_data
echo "All tests passed!"
