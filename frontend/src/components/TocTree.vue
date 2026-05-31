<script setup lang="ts">
import { ref } from 'vue'
import { ChevronRight, ChevronDown } from 'lucide-vue-next'

interface TocNode {
  node_id: string
  title: string
  level: number
  summary: string
  start_page: number | null
  end_page: number | null
  children?: TocNode[]
}

interface Props {
  nodes: TocNode[]
  currentPage: number
}

const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'select', page: number): void
}>()

// 展开的节点集合
const expandedNodes = ref<Set<string>>(new Set())

// 默认展开第一层
const initExpanded = () => {
  props.nodes.forEach(node => {
    if (!expandedNodes.value.has(node.node_id)) {
      expandedNodes.value.add(node.node_id)
    }
  })
}

// 初始化
initExpanded()

// 切换展开/折叠
const toggleNode = (nodeId: string, event: Event) => {
  event.stopPropagation()
  if (expandedNodes.value.has(nodeId)) {
    expandedNodes.value.delete(nodeId)
  } else {
    expandedNodes.value.add(nodeId)
  }
}

// 点击节点
const handleNodeClick = (node: TocNode) => {
  if (node.start_page) {
    emit('select', node.start_page)
  }
}

// 检查是否有子节点
const hasChildren = (node: TocNode): boolean => {
  return !!(node.children && node.children.length > 0)
}

// 检查是否展开
const isExpanded = (nodeId: string): boolean => {
  return expandedNodes.value.has(nodeId)
}

// 检查是否当前页
const isActive = (node: TocNode): boolean => {
  return node.start_page === props.currentPage
}
</script>

<template>
  <div class="toc-tree">
    <!-- 递归树节点组件 -->
    <template v-for="node in nodes" :key="node.node_id">
      <div class="tree-node">
        <!-- 节点内容 -->
        <div 
          class="tree-node-content"
          :class="{ active: isActive(node), 'has-page': node.start_page }"
          :style="{ paddingLeft: `${node.level * 16 + 8}px` }"
          @click="handleNodeClick(node)"
        >
          <!-- 展开按钮 -->
          <button 
            v-if="hasChildren(node)"
            class="expand-btn"
            @click.stop="toggleNode(node.node_id, $event)"
          >
            <ChevronDown v-if="isExpanded(node.node_id)" class="w-4 h-4" />
            <ChevronRight v-else class="w-4 h-4" />
          </button>
          <span v-else class="expand-placeholder" />
          
          <!-- 标题 -->
          <span class="node-title">{{ node.title }}</span>
          
          <!-- 页码 -->
          <span v-if="node.start_page" class="page-num">p.{{ node.start_page }}</span>
        </div>
        
        <!-- 子节点 -->
        <div 
          v-if="hasChildren(node) && isExpanded(node.node_id)" 
          class="tree-children"
        >
          <TocTree 
            :nodes="node.children || []" 
            :current-page="currentPage"
            @select="$emit('select', $event)"
          />
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.toc-tree {
  height: 100%;
  overflow-y: auto;
  padding: 8px 0;
}

.tree-node {
  user-select: none;
}

.tree-node-content {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 12px;
  cursor: pointer;
  border-radius: 6px;
  transition: all 0.2s;
  min-height: 36px;
}

.tree-node-content:hover {
  background: #242424;
}

.tree-node-content.has-page:hover {
  background: #1e3a5f;
}

.tree-node-content.active {
  background: #1e3a5f;
}

.expand-btn {
  width: 20px;
  height: 20px;
  padding: 0;
  background: transparent;
  border: none;
  color: #666;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  flex-shrink: 0;
}

.expand-btn:hover {
  background: #333;
  color: #a3a3a3;
}

.expand-placeholder {
  width: 20px;
  flex-shrink: 0;
}

.node-title {
  color: #e5e5e5;
  font-size: 13px;
  line-height: 1.4;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tree-node-content.active .node-title {
  color: #60a5fa;
}

.page-num {
  color: #3b82f6;
  font-size: 11px;
  flex-shrink: 0;
  padding: 2px 6px;
  background: rgba(59, 130, 246, 0.1);
  border-radius: 4px;
}

.tree-children {
  position: relative;
}

.tree-children::before {
  content: '';
  position: absolute;
  left: 15px;
  top: 0;
  bottom: 0;
  width: 1px;
  background: #333;
}
</style>
