export interface ToastMessage {
  id: number
  title: string
  message?: string
  tone: 'success' | 'error' | 'info'
}

let toastId = 0

export function useToast() {
  const messages = useState<ToastMessage[]>('global-toasts', () => [])

  function show(title: string, message = '', tone: ToastMessage['tone'] = 'info') {
    const id = ++toastId
    messages.value.push({ id, title, message, tone })
    setTimeout(() => dismiss(id), 4200)
  }

  function dismiss(id: number) {
    messages.value = messages.value.filter(item => item.id !== id)
  }

  return { messages, show, dismiss }
}

