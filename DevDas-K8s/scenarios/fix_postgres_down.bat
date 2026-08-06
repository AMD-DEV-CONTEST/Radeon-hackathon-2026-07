@echo off

echo ======================================
echo Fixing: PostgreSQL Down
echo ======================================

echo.
echo Scaling PostgreSQL back to 1 replica...
kubectl scale deployment postgres --replicas=1 -n devdas

echo.
echo Waiting for PostgreSQL...
kubectl rollout status deployment postgres -n devdas

echo.
echo Restarting payment-service...
kubectl rollout restart deployment payment-service -n devdas

echo.
echo Waiting for payment-service...
kubectl rollout status deployment payment-service -n devdas

echo.
echo Current pod status:
kubectl get pods -n devdas
echo.
echo Waiting for PostgreSQL pod to become Ready...
kubectl wait --for=condition=Ready pod -l app=postgres -n devdas --timeout=60s
pause