<script setup lang="ts">
import { computed } from 'vue'
import { FileText, FileType, FileCode, FileImage, FileSpreadsheet, Presentation, FileArchive, File } from 'lucide-vue-next'

interface Props {
  fileType: string
  size?: 'sm' | 'md' | 'lg'
}

const props = withDefaults(defineProps<Props>(), {
  size: 'md'
})

const iconConfig = computed(() => {
  const type = props.fileType.toLowerCase()
  
  // PDF
  if (type === '.pdf') {
    return {
      icon: FileText,
      color: 'text-red-500',
      bgColor: 'bg-red-50 dark:bg-red-950/30',
      borderColor: 'border-red-200 dark:border-red-800'
    }
  }
  
  // Word documents
  if (['.docx', '.doc'].includes(type)) {
    return {
      icon: FileType,
      color: 'text-blue-500',
      bgColor: 'bg-blue-50 dark:bg-blue-950/30',
      borderColor: 'border-blue-200 dark:border-blue-800'
    }
  }
  
  // Excel/Spreadsheets
  if (['.xlsx', '.xls', '.csv'].includes(type)) {
    return {
      icon: FileSpreadsheet,
      color: 'text-green-500',
      bgColor: 'bg-green-50 dark:bg-green-950/30',
      borderColor: 'border-green-200 dark:border-green-800'
    }
  }
  
  // PowerPoint/Presentations
  if (['.pptx', '.ppt', '.key'].includes(type)) {
    return {
      icon: Presentation,
      color: 'text-orange-500',
      bgColor: 'bg-orange-50 dark:bg-orange-950/30',
      borderColor: 'border-orange-200 dark:border-orange-800'
    }
  }
  
  // Markdown/Text/Code
  if (['.md', '.markdown', '.txt', '.json', '.js', '.ts', '.py', '.java', '.cpp', '.c', '.go', '.rs'].includes(type)) {
    return {
      icon: FileCode,
      color: 'text-gray-500',
      bgColor: 'bg-gray-50 dark:bg-gray-950/30',
      borderColor: 'border-gray-200 dark:border-gray-800'
    }
  }
  
  // Images
  if (['.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', '.bmp'].includes(type)) {
    return {
      icon: FileImage,
      color: 'text-purple-500',
      bgColor: 'bg-purple-50 dark:bg-purple-950/30',
      borderColor: 'border-purple-200 dark:border-purple-800'
    }
  }
  
  // Archives
  if (['.zip', '.rar', '.7z', '.tar', '.gz'].includes(type)) {
    return {
      icon: FileArchive,
      color: 'text-yellow-500',
      bgColor: 'bg-yellow-50 dark:bg-yellow-950/30',
      borderColor: 'border-yellow-200 dark:border-yellow-800'
    }
  }
  
  // Default
  return {
    icon: File,
    color: 'text-muted-foreground',
    bgColor: 'bg-muted',
    borderColor: 'border-transparent'
  }
})

const sizeClasses = computed(() => {
  switch (props.size) {
    case 'sm':
      return {
        container: 'w-8 h-8',
        icon: 'w-4 h-4'
      }
    case 'lg':
      return {
        container: 'w-16 h-16',
        icon: 'w-8 h-8'
      }
    default: // md
      return {
        container: 'w-10 h-10',
        icon: 'w-5 h-5'
      }
  }
})
</script>

<template>
  <div
    :class="[
      'rounded-lg flex items-center justify-center flex-shrink-0 border',
      iconConfig.bgColor,
      iconConfig.borderColor,
      sizeClasses.container
    ]"
  >
    <component
      :is="iconConfig.icon"
      :class="[iconConfig.color, sizeClasses.icon]"
    />
  </div>
</template>
