import { createRouter, createWebHistory, createWebHashHistory } from 'vue-router'
import { IS_STATIC } from '../static-mode'
import SectionStreamView from '../views/SectionStreamView.vue'
import WorkDocsView from '../views/WorkDocsView.vue'
import ReportListView from '../views/ReportListView.vue'
import ReportDetailView from '../views/ReportDetailView.vue'
import SettingsView from '../views/SettingsView.vue'
import DiscoveryView from '../views/DiscoveryView.vue'
import DiscoveryDetailView from '../views/DiscoveryDetailView.vue'
import ICResearchView from '../views/ICResearchView.vue'
import TechnologyTopicView from '../views/TechnologyTopicView.vue'
import PersonalLibraryView from '../views/PersonalLibraryView.vue'
import ResearchAnalysisView from '../views/ResearchAnalysisView.vue'
import TechnologyOverviewView from '../views/TechnologyOverviewView.vue'
import { isWeeklySection } from '../sections'
import { loadWorkspace, workspace } from '../workspace'
import { HBM_TOPIC_ID } from '../hbm-topic'

export const router = createRouter({
  history: IS_STATIC ? createWebHashHistory() : createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: TechnologyOverviewView },
    {
      path: '/observations/editor',
      redirect: (to) => {
        const draftId = typeof to.query.draft === 'string' ? to.query.draft : ''
        return {
          name: 'home',
          query: draftId.endsWith('-daily') || to.query.kind === 'daily' ? { view: 'daily' } : {},
        }
      },
    },
    { path: '/explore/ic', name: 'ic-exploration', component: ICResearchView },
    { path: '/explore/ic/topics/:topicId', name: 'ic-technology-topic', component: TechnologyTopicView, props: true },
    { path: '/discover', name: 'discover', component: DiscoveryView },
    { path: '/library', name: 'library', component: PersonalLibraryView },
    { path: '/analysis', name: 'research-analysis', component: ResearchAnalysisView },
    { path: '/discover/item/:id', name: 'discover-detail', component: DiscoveryDetailView, props: true },
    {
      path: '/sections/:key',
      name: 'section',
      component: SectionStreamView,
      meta: { requiresReports: true },
      // key 是 Vue 保留属性名,不能作为 prop 传递,映射为 sectionKey
      props: (route) => ({ sectionKey: route.params.key }),
    },
    {
      path: '/sections-weekly/:key',
      name: 'section-weekly',
      meta: { requiresReports: true },
      component: SectionStreamView,
      props: (route) => ({ sectionKey: route.params.key }),
    },
    { path: '/workdocs', name: 'workdocs', component: WorkDocsView },
    {
      path: '/archive',
      name: 'list',
      meta: { requiresReports: true },
      component: ReportListView,
    },
    {
      path: '/archive-weekly',
      name: 'list-weekly',
      meta: { requiresReports: true },
      component: ReportListView,
    },
    { path: '/report/:id', name: 'detail', component: ReportDetailView, props: true, meta: { requiresReports: true } },
    { path: '/settings', name: 'settings', component: SettingsView },
    { path: '/:pathMatch(.*)*', redirect: '/discover' },
  ],
  scrollBehavior(to) {
    return to.hash === '#tracked-topics' ? { el: to.hash, top: 16 } : { top: 0 }
  },
})

router.afterEach((to) => {
  const titles: Record<string, string> = {
    home: '热点与技术观察',
    library: '我的收藏',
    'research-analysis': '相关性分析',
    'ic-exploration': '技术专题与评价',
    'ic-technology-topic': '技术专题',
    discover: '每日发现',
    'discover-detail': '资料详情',
    workdocs: '工作文档',
    list: '历史日报',
    'list-weekly': '历史周报',
    settings: '模型设置',
  }
  document.title = `${titles[String(to.name)] || '报告栏目'} · 科研信息工作台`
})

// 栏目与路径前缀不匹配时重定向到正确前缀(weekly 栏目 ↔ /sections-weekly)
router.beforeEach(async (to) => {
  if (IS_STATIC && ['workdocs', 'settings'].includes(String(to.name))) return { name: 'research-analysis', replace: true }
  await loadWorkspace()
  if (to.name === 'home' && to.query.sample === HBM_TOPIC_ID && workspace.domain === 'ic') {
    return { name: 'ic-technology-topic', params: { topicId: HBM_TOPIC_ID }, replace: true }
  }
  if (to.name === 'ic-technology-topic' && workspace.domain !== 'ic') return { name: 'home', replace: true }
  if (to.meta.requiresReports && !workspace.reportsEnabled) {
    return { name: 'discover', replace: true }
  }
  if (to.name === 'section' && isWeeklySection(String(to.params.key))) {
    return { name: 'section-weekly', params: to.params }
  }
  if (to.name === 'section-weekly' && !isWeeklySection(String(to.params.key))) {
    return { name: 'section', params: to.params }
  }
})
