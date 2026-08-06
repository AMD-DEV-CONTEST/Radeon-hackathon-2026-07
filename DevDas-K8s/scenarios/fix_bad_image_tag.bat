@echo off

echo ======================================
echo Fixing: Bad Image
echo ======================================

kubectl set image deployment/payment-service payment-service=payment-service:v1 -n devdas

echo.
echo Exit code: %ERRORLEVEL%

kubectl rollout restart deployment/payment-service -n devdas

echo.
kubectl rollout status deployment/payment-service -n devdas

echo.
kubectl get pods -n devdas

pause