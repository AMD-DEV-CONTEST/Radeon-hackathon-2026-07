<script setup lang="ts">
import { watch } from 'vue'
import { useLoadingBar } from 'naive-ui'
import { useUiStore } from '@/stores/ui'

const loadingBar = useLoadingBar()
const uiStore = useUiStore()

watch(
  () => uiStore.globalLoading,
  (loading) => {
    if (loading) {
      loadingBar.start()
    } else {
      loadingBar.finish()
    }
  }
)
</script>
