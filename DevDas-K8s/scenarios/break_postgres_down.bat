@echo off

echo ======================================
echo Breaking: PostgreSQL Down
echo ======================================

echo.
echo Scaling PostgreSQL to 0 replicas...
kubectl scale deployment postgres --replicas=0 -n devdas

echo.
echo Restarting payment-service...
kubectl rollout restart deployment/payment-service -n devdas

echo.
echo Waiting for payment-service rollout...
kubectl rollout status deployment/payment-service -n devdas

echo.
echo Current pod status:
kubectl get pods -n devdas

pause