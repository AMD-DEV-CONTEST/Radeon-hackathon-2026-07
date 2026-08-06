@echo off

echo ======================================
echo Breaking: Invalid Image
echo ======================================

kubectl set image deployment/payment-service ^
payment-service=payment-service:this-tag-does-not-exist ^
-n devdas

echo.
kubectl rollout restart deployment payment-service -n devdas

echo.
kubectl get pods -n devdas

pause