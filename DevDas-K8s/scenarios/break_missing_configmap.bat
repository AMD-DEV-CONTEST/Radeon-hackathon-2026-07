@echo off
echo ======================================
echo Breaking: Missing ConfigMap
echo ======================================

kubectl delete configmap payment-config -n devdas

echo.
echo Restarting payment-service...
kubectl rollout restart deployment/payment-service -n devdas

echo.
kubectl get pods -n devdas

pause