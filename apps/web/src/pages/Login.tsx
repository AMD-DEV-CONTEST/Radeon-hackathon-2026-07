import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Bot, LogIn, UserPlus, Loader2, Eye, EyeOff } from 'lucide-react'

import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { Input } from '../components/ui/input'
import { useAuth } from '../lib/authContext'

type Mode = 'login' | 'register'

const loginSchema = z.object({
  identifier: z.string().min(1, '请输入账号'),
  password: z.string().min(1, '请输入密码'),
})

const registerSchema = z.object({
  username: z
    .string()
    .min(3, '至少 3 个字符')
    .max(20, '最多 20 个字符')
    .regex(/^[a-zA-Z0-9_]+$/, '只能包含字母、数字和下划线'),
  email: z.string().email('请输入有效邮箱'),
  password: z
    .string()
    .min(8, '至少 8 个字符')
    .regex(/[A-Za-z]/, '需要包含字母')
    .regex(/\d/, '需要包含数字'),
})

type LoginForm = z.infer<typeof loginSchema>
type RegisterForm = z.infer<typeof registerSchema>

export function Login() {
  const { login, register: apiRegister } = useAuth()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [mode, setMode] = useState<Mode>(params.get('mode') === 'register' ? 'register' : 'login')
  const [serverErr, setServerErr] = useState<string | null>(null)
  const [showPwd, setShowPwd] = useState(false)

  const redirect = params.get('redirect') || '/'

  const loginForm = useForm<LoginForm>({
    resolver: zodResolver(loginSchema),
    defaultValues: { identifier: '', password: '' },
  })

  const registerForm = useForm<RegisterForm>({
    resolver: zodResolver(registerSchema),
    defaultValues: { username: '', email: '', password: '' },
  })

  const activeForm = mode === 'login' ? loginForm : registerForm
  const isSubmitting = activeForm.formState.isSubmitting

  const onLoginSubmit = async (data: LoginForm) => {
    setServerErr(null)
    try {
      await login(data.identifier, data.password)
      navigate(redirect, { replace: true })
    } catch (ex) {
      setServerErr((ex as Error).message)
    }
  }

  const onRegisterSubmit = async (data: RegisterForm) => {
    setServerErr(null)
    try {
      await apiRegister(data)
      navigate(redirect, { replace: true })
    } catch (ex) {
      setServerErr((ex as Error).message)
    }
  }

  const switchMode = (next: Mode) => {
    setServerErr(null)
    loginForm.reset()
    registerForm.reset()
    setMode(next)
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center space-y-2">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-[hsl(var(--primary))]/15">
            <Bot className="h-8 w-8 text-[hsl(var(--primary))]" />
          </div>
          <CardTitle className="text-2xl">Botverse X</CardTitle>
          <div className="text-xs text-muted-foreground">
            {mode === 'login' ? '登录你的账号' : '创建一个新账号'}
          </div>
        </CardHeader>
        <CardContent>
          {mode === 'login' ? (
            <form onSubmit={loginForm.handleSubmit(onLoginSubmit)} className="space-y-3">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">账号（用户名或邮箱）</label>
                <Input
                  autoFocus
                  placeholder="用户名或邮箱"
                  autoComplete="username"
                  {...loginForm.register('identifier')}
                />
                {loginForm.formState.errors.identifier && (
                  <p className="text-xs text-red-400">{loginForm.formState.errors.identifier.message}</p>
                )}
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">密码</label>
                <div className="relative">
                  <Input
                    type={showPwd ? 'text' : 'password'}
                    placeholder="••••••••"
                    autoComplete="current-password"
                    {...loginForm.register('password')}
                  />
                  <button
                    type="button"
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    onClick={() => setShowPwd(!showPwd)}
                    tabIndex={-1}
                  >
                    {showPwd ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
                {loginForm.formState.errors.password && (
                  <p className="text-xs text-red-400">{loginForm.formState.errors.password.message}</p>
                )}
              </div>

              {serverErr && (
                <div role="alert" className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
                  {serverErr}
                </div>
              )}

              <Button type="submit" disabled={isSubmitting} className="w-full">
                {isSubmitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <LogIn className="mr-2 h-4 w-4" />}
                {isSubmitting ? '登录中…' : '登录'}
              </Button>

              <div className="text-center text-xs text-muted-foreground">
                还没有账号?{' '}
                <button type="button" className="text-[hsl(var(--primary))] hover:underline" onClick={() => switchMode('register')}>
                  注册
                </button>
              </div>
            </form>
          ) : (
            <form onSubmit={registerForm.handleSubmit(onRegisterSubmit)} className="space-y-3">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">用户名</label>
                <Input
                  autoFocus
                  placeholder="字母、数字或下划线"
                  autoComplete="username"
                  {...registerForm.register('username')}
                />
                {registerForm.formState.errors.username && (
                  <p className="text-xs text-red-400">{registerForm.formState.errors.username.message}</p>
                )}
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">邮箱</label>
                <Input
                  type="email"
                  placeholder="name@example.com"
                  autoComplete="email"
                  {...registerForm.register('email')}
                />
                {registerForm.formState.errors.email && (
                  <p className="text-xs text-red-400">{registerForm.formState.errors.email.message}</p>
                )}
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">密码</label>
                <div className="relative">
                  <Input
                    type={showPwd ? 'text' : 'password'}
                    placeholder="≥8 字符，含字母和数字"
                    autoComplete="new-password"
                    {...registerForm.register('password')}
                  />
                  <button
                    type="button"
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    onClick={() => setShowPwd(!showPwd)}
                    tabIndex={-1}
                  >
                    {showPwd ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
                {registerForm.formState.errors.password && (
                  <p className="text-xs text-red-400">{registerForm.formState.errors.password.message}</p>
                )}
              </div>

              {serverErr && (
                <div role="alert" className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
                  {serverErr}
                </div>
              )}

              <Button type="submit" disabled={isSubmitting} className="w-full">
                {isSubmitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <UserPlus className="mr-2 h-4 w-4" />}
                {isSubmitting ? '注册中…' : '注册并登录'}
              </Button>

              <div className="text-center text-xs text-muted-foreground">
                已有账号?{' '}
                <button type="button" className="text-[hsl(var(--primary))] hover:underline" onClick={() => switchMode('login')}>
                  返回登录
                </button>
              </div>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
