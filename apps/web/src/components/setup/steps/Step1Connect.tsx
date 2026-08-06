import { Step1Camera } from './Step1Camera'
import { Step2Arm } from './Step2Arm'
import { SetupStepCard } from '../SetupStepCard'
import { useSetup } from '../SetupProvider'

export function Step1Connect() {
  const { state, goNext } = useSetup()
  const ready = state.camera !== null && state.followerPort !== null && state.leaderPort !== null

  return (
    <SetupStepCard
      stepId="connect"
      title="连接设备"
      description="先选摄像头，再识别主控臂和执行臂。准备好后进入遥操作试运行。"
      nextDisabled={!ready}
      nextLabel={ready ? '下一步：遥操作试运行' : '请先完成相机和两只机械臂'}
      hidePrev
      onNext={goNext}
    >
      <div className="grid gap-4">
        <Step1Camera embedded />
        <Step2Arm embedded />
      </div>
    </SetupStepCard>
  )
}
