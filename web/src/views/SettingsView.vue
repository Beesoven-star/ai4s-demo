<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { analysisRequest, type ModelConnection } from '../api/analysis'

const form=reactive({base_url:'https://api.deepseek.com',model:'deepseek-flash',api_key:''})
const connection=ref<ModelConnection|null>(null)
const loading=ref(true),saving=ref(false),testing=ref(false),error=ref(''),notice=ref('')
const savedSignature=ref('')
function signature(){return JSON.stringify({base_url:form.base_url,model:form.model})}
onMounted(async()=>{
  try {
    connection.value=await analysisRequest<ModelConnection>('/connection')
    form.base_url=connection.value.base_url;form.model=connection.value.model;savedSignature.value=signature()
  } catch(e){error.value=e instanceof Error ? e.message : '连接设置加载失败'}
  finally{loading.value=false}
})
async function save(){
  saving.value=true;error.value='';notice.value=''
  try{
    connection.value=await analysisRequest<ModelConnection>('/connection',{...form},'PUT')
    form.api_key='';savedSignature.value=signature();notice.value='连接设置已保存，可测试连接后前往相关性分析。'
  } catch(e){error.value=e instanceof Error ? e.message : '保存失败'}
  finally{saving.value=false}
}
async function test(){
  testing.value=true;error.value='';notice.value=''
  try{const result=await analysisRequest<{message:string}>('/connection/test',{});notice.value=result.message}
  catch(e){error.value=e instanceof Error ? e.message : '连接测试失败'}
  finally{testing.value=false}
}
</script>

<template>
  <div>
    <header class="mb-7"><h2 class="font-serif text-3xl font-bold">设置</h2><div class="mt-5 border-t-2 border-stone-900 dark:border-stone-100" /></header>
    <p v-if="loading" role="status" class="py-12 text-sm text-stone-500">正在加载…</p>
    <form v-else class="max-w-xl" @submit.prevent="save">
      <h3 class="font-serif text-xl font-semibold">相关性分析使用的模型服务</h3>
      <p class="mt-2 text-sm text-stone-500">用于分析你选中的文献和新闻，采集与去重独立运行。</p>
      <label for="analysis-base-url" class="mt-6 block text-sm">服务地址</label>
      <input id="analysis-base-url" v-model="form.base_url" type="url" required spellcheck="false" class="mt-2 w-full border border-stone-300 bg-transparent px-3 py-2.5 text-sm dark:border-stone-700" placeholder="https://api.deepseek.com" />
      <p class="mt-2 text-xs text-stone-400">填写兼容 Chat Completions 的基础地址，不含 /chat/completions。第三方服务请使用其提供的地址。</p>
      <label for="llm-model" class="mt-5 block text-sm">模型名称</label>
      <input id="llm-model" v-model="form.model" type="text" required spellcheck="false" class="mt-2 w-full border border-stone-300 bg-transparent px-3 py-2.5 font-mono text-sm dark:border-stone-700" placeholder="deepseek-flash" />
      <p class="mt-2 text-xs text-stone-400">使用服务商提供的准确模型标识。<a href="https://api-docs.deepseek.com/" target="_blank" rel="noopener noreferrer" class="text-accent underline">DeepSeek 官方文档 ↗</a></p>
      <label for="analysis-api-key" class="mt-5 block text-sm">API 密钥 <span class="ml-2 text-xs text-stone-400">{{ connection?.key_configured ? '已配置，留空保留' : '尚未配置' }}</span></label>
      <input id="analysis-api-key" v-model="form.api_key" type="password" autocomplete="new-password" spellcheck="false" class="mt-2 w-full border border-stone-300 bg-transparent px-3 py-2.5 text-sm dark:border-stone-700" :placeholder="connection?.key_configured ? '留空保留已配置密钥' : '在此填写密钥，不要发到聊天里'" />
      <p class="mt-2 text-xs leading-6 text-stone-400">密钥仅保存在本机连接配置中，不回显、不写入报告，已排除在 Git 提交之外。</p>
      <div class="mt-6 flex flex-wrap items-center gap-3"><button type="submit" :disabled="saving || testing" class="bg-accent px-5 py-2.5 text-sm text-white disabled:opacity-50">{{ saving ? '保存中…' : '保存连接设置' }}</button><button type="button" :disabled="saving || testing || !connection?.key_configured || !!form.api_key || signature()!==savedSignature" class="border border-stone-300 px-4 py-2.5 text-sm disabled:opacity-50 dark:border-stone-700" @click="test">{{ testing ? '正在测试…' : '测试连接' }}</button><router-link to="/analysis" class="text-sm text-accent">前往相关性分析 →</router-link></div>
      <p class="mt-3 text-xs text-stone-400">测试连接会发送一次简短请求；生成分析会发送选中资料的题名与摘要/简介，按服务商规则计费。</p>
      <p v-if="notice" role="status" class="mt-4 text-sm text-green-700 dark:text-green-400">{{ notice }}</p>
    </form>
    <p v-if="error" role="alert" class="mt-4 text-sm text-red-600">{{ error }}</p>
  </div>
</template>
