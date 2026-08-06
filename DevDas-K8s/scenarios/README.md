Scenario	Expected Pod Status	Expected Root Cause
Missing ConfigMap	CreateContainerConfigError	Missing ConfigMap
Missing Secret	CreateContainerConfigError	Missing Secret
Wrong DATABASE_URL	CrashLoopBackOff	Database connection failure
Postgres Down	CrashLoopBackOff	PostgreSQL unavailable
Wrong Image Tag	ErrImagePull / ImagePullBackOff	Image pull failure
Wrong Image	CrashLoopBackOff	Application startup failure
Remove Service	CrashLoopBackOff	PostgreSQL service not found