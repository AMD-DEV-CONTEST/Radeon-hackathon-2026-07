import { useState, useEffect } from 'react'
import {
  ConfigProvider, theme, Layout, Menu, Avatar, Badge, Switch,
  Breadcrumb, Card, Form, Input, Button, Space, Typography,
} from 'antd'
import {
  RobotOutlined, SafetyOutlined, BellOutlined, UserOutlined,
  BulbFilled, BulbOutlined, LogoutOutlined, BookOutlined,
  MessageOutlined, GlobalOutlined,
} from '@ant-design/icons'
import AgentActivity from './components/AgentActivity'
import ApprovalCenter from './components/ApprovalCenter'
import RiskRules from './components/RiskRules'
import KnowledgeBase from './components/KnowledgeBase'
import ChatConsole from './components/ChatConsole'
import { dataCache } from './dataCache'
import { useI18n } from './i18n'
import './App.css'

const { Sider, Header, Content } = Layout
const { Title } = Typography

function LoginPage({ onLogin }: { onLogin: (name: string) => void }) {
  const { t } = useI18n()
  const [loading, setLoading] = useState(false)
  return (
    <div style={{
      display: 'flex', justifyContent: 'center', alignItems: 'center',
      height: '100vh', background: '#0f172a',
    }}>
      <Card style={{ width: 380 }}>
        <Title level={3} style={{ textAlign: 'center', color: '#38bdf8' }}>
          {t('app.title')}
        </Title>
        <Form
          onFinish={(v: any) => {
            setLoading(true)
            setTimeout(() => { onLogin(v.username || 'admin'); setLoading(false) }, 300)
          }}
        >
          <Form.Item name="username" rules={[{ required: true, message: t('app.usernameRequired') }]}>
            <Input prefix={<UserOutlined />} placeholder={t('app.usernamePlaceholder')} size="large" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: t('app.passwordRequired') }]}>
            <Input.Password prefix={<SafetyOutlined />} placeholder={t('app.passwordPlaceholder')} size="large" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block size="large" loading={loading}>
            {t('app.login')}
          </Button>
        </Form>
      </Card>
    </div>
  )
}

function App() {
  const { t, lang, setLang } = useI18n()
  const [logged, setLogged] = useState(() => !!localStorage.getItem('aiops_user'))
  const [user, setUser] = useState(() => localStorage.getItem('aiops_user') || 'admin')
  const [collapsed, setCollapsed] = useState(false)
  const [darkMode, setDarkMode] = useState(true)
  const [tab, setTab] = useState('agent')
  const [pendingCount, setPendingCount] = useState(0)

  useEffect(() => {
    const fetchPending = async () => {
      try {
        const data = await dataCache.fetch<any[]>(
          'approvals_pending',
          async () => {
            const res = await fetch('/api/approvals?status=pending')
            return res.json()
          },
          5000
        )
        setPendingCount(Array.isArray(data) ? data.length : 0)
      } catch (e) {
        console.error('fetch pending approvals failed:', e)
      }
    }
    fetchPending()
    const timer = setInterval(fetchPending, 10000)
    return () => clearInterval(timer)
  }, [])

  if (!logged) {
    return (
      <ConfigProvider theme={{ algorithm: theme.darkAlgorithm }}>
        <LoginPage onLogin={(name) => {
          localStorage.setItem('aiops_user', name)
          setUser(name); setLogged(true)
        }} />
      </ConfigProvider>
    )
  }

  const menuItems = [
    { key: 'agent', icon: <RobotOutlined />, label: t('menu.agent') },
    { key: 'chat', icon: <MessageOutlined />, label: t('menu.chat') },
    { key: 'approval', icon: <SafetyOutlined />, label: t('menu.approval') },
    { key: 'rules', icon: <BulbOutlined />, label: t('menu.rules') },
    { key: 'kb', icon: <BookOutlined />, label: t('menu.kb') },
  ]
  const currentLabel = menuItems.find(m => m.key === tab)?.label || ''

  return (
    <ConfigProvider theme={{
      algorithm: darkMode ? theme.darkAlgorithm : theme.defaultAlgorithm,
      token: { colorPrimary: '#0ea5e9' },
    }}>
      <Layout style={{ height: '100vh', overflow: 'hidden' }}>
        <Sider
          collapsible
          collapsed={collapsed}
          onCollapse={setCollapsed}
          theme={darkMode ? 'dark' : 'light'}
          width={200}
        >
          <div style={{
            height: 56, display: 'flex', alignItems: 'center',
            justifyContent: 'center', color: '#38bdf8',
            fontWeight: 700, fontSize: collapsed ? 14 : 15,
            borderBottom: '1px solid rgba(255,255,255,0.06)',
          }}>
            {collapsed ? 'AIOps' : t('app.title')}
          </div>
          <Menu
            theme={darkMode ? 'dark' : 'light'}
            mode="inline"
            selectedKeys={[tab]}
            items={menuItems}
            onClick={(e) => setTab(e.key)}
          />
        </Sider>

        <Layout style={{ overflow: 'hidden', display: 'flex', flexDirection: 'column', height: '100%' }}>
          <Header style={{
            display: 'flex', alignItems: 'center',
            justifyContent: 'flex-end', padding: '0 24px', flexShrink: 0,
          }}>
            <Space size="large">
              <Button
                type="text" size="small"
                icon={<GlobalOutlined />}
                onClick={() => setLang(lang === 'zh' ? 'en' : 'zh')}
              >
                {lang === 'zh' ? 'EN' : '中文'}
              </Button>
              <Badge count={pendingCount} size="small">
                <BellOutlined style={{ fontSize: 18 }} />
              </Badge>
              <Switch
                checked={darkMode}
                onChange={setDarkMode}
                checkedChildren={<BulbFilled />}
                unCheckedChildren={<BulbOutlined />}
              />
              <Space>
                <Avatar size="small" icon={<UserOutlined />} />
                <span style={{ fontSize: 14 }}>{user}</span>
              </Space>
              <Button
                type="text" size="small"
                icon={<LogoutOutlined />}
                onClick={() => {
                  localStorage.removeItem('aiops_user')
                  setLogged(false)
                }}
              />
            </Space>
          </Header>

          <div style={{ padding: '10px 24px 8px', flexShrink: 0 }}>
            <Breadcrumb items={[{ title: t('app.home') }, { title: currentLabel }]} />
          </div>

          <Content style={{
            flex: 1, overflow: 'hidden', padding: '12px 20px',
            position: 'relative', minHeight: 0,
          }}>
            {tab === 'agent' && (
              <div style={{ position: 'absolute', inset: 0, display: 'flex' }}>
                <AgentActivity />
              </div>
            )}
            {tab === 'approval' && (
              <div style={{ position: 'absolute', inset: 0 }}>
                <ApprovalCenter />
              </div>
            )}
            {tab === 'chat' && (
              <div style={{ position: 'absolute', inset: 0, display: 'flex' }}>
                <ChatConsole />
              </div>
            )}
            {tab === 'rules' && (
              <div style={{ position: 'absolute', inset: 0 }}>
                <RiskRules />
              </div>
            )}
            {tab === 'kb' && (
              <div style={{ position: 'absolute', inset: 0 }}>
                <KnowledgeBase />
              </div>
            )}
          </Content>
        </Layout>
      </Layout>
    </ConfigProvider>
  )
}

export default App
