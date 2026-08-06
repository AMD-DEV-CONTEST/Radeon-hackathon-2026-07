@echo off
echo ======================================
echo Breaking: Missing Secret
echo ======================================

kubectl delete secret payment-secret -n devdas

echo.
echo Restarting payment-service...
kubectl rollout restart deployment/payment-service -n devdas

echo.
kubectl get pods -n devdas

pause