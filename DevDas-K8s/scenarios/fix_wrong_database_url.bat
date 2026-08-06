@echo off

echo ======================================
echo Fixing: Wrong DATABASE_URL
echo ======================================

kubectl delete configmap payment-config -n devdas

kubectl create configmap payment-config ^
--from-literal=DATABASE_URL="postgresql://admin:password@postgres:5432/postgres" ^
-n devdas

echo.
echo Restarting payment-service...
kubectl rollout restart deployment/payment-service -n devdas

echo.
echo Waiting for rollout...
kubectl rollout status deployment/payment-service -n devdas

echo.
echo Current pod status:
kubectl get pods -n devdas

pause