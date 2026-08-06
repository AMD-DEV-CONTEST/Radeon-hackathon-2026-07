@echo off
echo ======================================
echo Fixing: Missing ConfigMap
echo ======================================

kubectl create configmap payment-config ^
--from-literal=DATABASE_URL="postgresql://admin:password@postgres:5432/postgres" ^
-n devdas

echo.
echo Restarting payment-service...
kubectl rollout restart deployment/payment-service -n devdas

echo.
kubectl rollout status deployment/payment-service -n devdas

echo.
kubectl get pods -n devdas

echo.
echo ConfigMap restored.
pause