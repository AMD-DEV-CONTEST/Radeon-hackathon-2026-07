"""Profile CRUD."""
from services.db import get_db
from services.prompt_engine.presets import get_builtin_profiles
class PromptProfileManager:
    def list(s,tt=None):
        db=get_db()
        if tt:r=db.execute("SELECT*FROM prompt_profiles WHERE task_type IN(?,'all')ORDER BY is_builtin DESC,name",(tt,)).fetchall()
        else:r=db.execute("SELECT*FROM prompt_profiles ORDER BY is_builtin DESC,name").fetchall()
        db.close();return[dict(x)for x in r]
    def get(s,pid):
        db=get_db();r=db.execute("SELECT*FROM prompt_profiles WHERE profile_id=?",(pid,)).fetchone();db.close()
        return dict(r)if r else{}
    def get_active(s,tt=None):
        db=get_db()
        if tt:r=db.execute("SELECT*FROM prompt_profiles WHERE is_active=1 AND task_type IN(?,'all')LIMIT 1",(tt,)).fetchone()
        else:r=db.execute("SELECT*FROM prompt_profiles WHERE is_active=1 LIMIT 1").fetchone()
        db.close();return dict(r)if r else{}
    def create(s,pid,name,content,tt="all",st="global",desc=""):
        db=get_db();db.execute("INSERT INTO prompt_profiles(profile_id,name,description,scope_type,task_type,content,is_builtin)VALUES(?,?,?,?,?,?,0)",(pid,name,desc,st,tt,content))
        db.execute("INSERT INTO prompt_profile_versions(profile_id,version,content)VALUES(?,1,?)",(pid,content));db.commit();db.close()
        return{"profile_id":pid}
    def update(s,pid,content=None,name=None):
        db=get_db()
        if name:db.execute("UPDATE prompt_profiles SET name=?,updated_at=CURRENT_TIMESTAMP WHERE profile_id=?",(name,pid))
        if content:
            v=db.execute("SELECT version FROM prompt_profiles WHERE profile_id=?",(pid,)).fetchone()[0]+1
            db.execute("UPDATE prompt_profiles SET content=?,version=?,updated_at=CURRENT_TIMESTAMP WHERE profile_id=?",(content,v,pid))
            db.execute("INSERT INTO prompt_profile_versions(profile_id,version,content)VALUES(?,?,?)",(pid,v,content))
        db.commit();db.close();return{"status":"updated"}
    def activate(s,pid):
        db=get_db();db.execute("UPDATE prompt_profiles SET is_active=0");db.execute("UPDATE prompt_profiles SET is_active=1 WHERE profile_id=?",(pid,));db.commit();db.close()
    def seed_builtins(s):
        db=get_db()
        if db.execute("SELECT COUNT(*)FROM prompt_profiles").fetchone()[0]==0:
            for p in get_builtin_profiles():
                db.execute("INSERT INTO prompt_profiles(profile_id,name,description,scope_type,task_type,content,is_builtin,version)VALUES(?,?,?,?,?,?,1,1)",(p["profile_id"],p["name"],"",p.get("scope_type","global"),p.get("task_type","all"),p["content"]))
            db.commit()
        db.close()
