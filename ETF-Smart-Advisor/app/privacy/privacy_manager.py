# app/privacy/privacy_manager.py
"""
Privacy Protection and Permission Control
"""

import re
import hashlib
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from collections import defaultdict
import json
from pathlib import Path
from ..config import PRIVACY_CONFIG, DATA_DIR


class PrivacyManager:
    """隐私保护管理器"""
    
    def __init__(self):
        self.enabled = PRIVACY_CONFIG.get("enabled", True)
        self.retention_days = PRIVACY_CONFIG.get("data_retention_days", 30)
        self.anonymize = PRIVACY_CONFIG.get("anonymize_data", True)
        self.local_only = PRIVACY_CONFIG.get("local_only", True)
        
        self.audit_log_path = DATA_DIR / "audit_log.json"
        self._load_audit_log()
        
        print(f"🔒 Privacy protection is enabled")
        print(f"   📅 Data retention: {self.retention_days} days")
        print(f"   🎭 Data anonymization: {'Enabled' if self.anonymize else 'Disabled'}")
        print(f"   🏠 Local storage: {'Enabled' if self.local_only else 'Disabled'}")
    
    def _load_audit_log(self):
        """加载审计日志"""
        if self.audit_log_path.exists():
            try:
                with open(self.audit_log_path, 'r', encoding='utf-8') as f:
                    self.audit_log = json.load(f)
                return
            except:
                pass
        self.audit_log = []
    
    def _save_audit_log(self):
        """保存审计日志"""
        try:
            with open(self.audit_log_path, 'w', encoding='utf-8') as f:
                json.dump(self.audit_log[-1000:], f, ensure_ascii=False, indent=2)
        except:
            pass
    
    def anonymize_text(self, text: str) -> str:
        """文本脱敏"""
        if not self.anonymize:
            return text
        
        # 脱敏邮箱
        text = re.sub(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '[EMAIL]', text)
        
        # 脱敏手机号
        text = re.sub(r'1[3-9]\d{9}', '[PHONE]', text)
        
        # 脱敏身份证
        text = re.sub(r'\d{17}[\dXx]', '[ID_CARD]', text)
        
        # 脱敏 IP
        text = re.sub(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', '[IP]', text)
        
        return text
    
    def anonymize_symbol(self, symbol: str) -> str:
        """股票代码脱敏"""
        if not self.anonymize:
            return symbol
        
        # 只保留前两位和后两位
        if len(symbol) >= 6:
            return f"{symbol[:2]}***{symbol[-2:]}"
        return symbol
    
    def log_access(self, user_id: str, action: str, resource: str, 
                   details: Optional[Dict] = None):
        """记录访问日志"""
        if not self.enabled:
            return
        
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'user_id': hashlib.sha256(user_id.encode()).hexdigest()[:16],
            'action': action,
            'resource': resource,
            'details': self.anonymize_text(json.dumps(details)) if details else None
        }
        
        self.audit_log.append(log_entry)
        self._save_audit_log()
    
    def check_permission(self, user_id: str, action: str, resource: str) -> bool:
        """检查权限"""
        # 简单权限控制：默认所有用户有读权限
        if action in ['read', 'search', 'get']:
            return True
        
        # 写操作需要特殊权限
        if action in ['write', 'delete', 'update']:
            # 这里可以接入更复杂的权限系统
            return user_id in ['admin', 'system']
        
        return False
    
    def cleanup_old_data(self):
        """清理过期数据"""
        if not self.enabled:
            return
        
        cutoff = datetime.now() - timedelta(days=self.retention_days)
        cutoff_str = cutoff.isoformat()
        
        # 清理审计日志
        self.audit_log = [
            entry for entry in self.audit_log
            if entry.get('timestamp', '') > cutoff_str
        ]
        self._save_audit_log()
    
    def get_audit_report(self) -> Dict:
        """获取审计报告"""
        return {
            'total_entries': len(self.audit_log),
            'last_7_days': len([
                e for e in self.audit_log
                if e.get('timestamp', '') > (datetime.now() - timedelta(days=7)).isoformat()
            ]),
            'actions': list(set(e.get('action') for e in self.audit_log)),
            'users': list(set(e.get('user_id') for e in self.audit_log)),
            'retention_days': self.retention_days,
        }