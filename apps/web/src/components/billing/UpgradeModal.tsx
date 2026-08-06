import { Modal } from '../ui/modal'
import { Button } from '../ui/button'
import type { SubscriptionTier } from '../../lib/entitlements'

interface UpgradeModalProps {
  open: boolean
  onClose: () => void
  requiredTier?: SubscriptionTier
  reason?: string
}

export function UpgradeModal({ open, onClose, reason }: UpgradeModalProps) {
  return (
    <Modal isOpen={open} onClose={onClose} title="内测期间全部免费">
      <div className="space-y-4 text-sm">
        {reason && <p className="text-muted-foreground">{reason}</p>}
        <p>
          当前处于<strong>内测阶段</strong>，注册即可使用平台功能，暂不需要付费或升级套餐。
        </p>
        <p className="text-xs text-muted-foreground">
          若某功能提示权限不足，请刷新页面或重新登录；仍有问题可点右下角 Copilot 求助。
        </p>
        <div className="flex justify-end">
          <Button onClick={onClose}>知道了</Button>
        </div>
      </div>
    </Modal>
  )
}
