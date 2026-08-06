@echo off
echo ======================================
echo Fixing: Missing Secret
echo ======================================

kubectl delete secret payment-secret -n devdas --ignore-not-found

kubectl create secret generic payment-secret ^
--from-literal=POSTGRES_USER=admin ^
--from-literal=POSTGRES_PASSWORD=password ^
-n devdas

echo.
echo Restarting payment-service...
kubectl rollout restart deployment/payment-service -n devdas

echo.
kubectl rollout status deployment/payment-service -n devdas

echo.
kubectl get pods -n devdas

pause