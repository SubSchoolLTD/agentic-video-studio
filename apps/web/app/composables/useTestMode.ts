export function useTestMode() {
  const cookie = useCookie<boolean>('avs_admin_test_mode', {
    default: () => false,
    sameSite: 'lax',
    secure: !import.meta.dev,
    maxAge: 60 * 60 * 12,
  })
  const enabled = computed({
    get: () => Boolean(cookie.value),
    set: value => { cookie.value = Boolean(value) },
  })
  return { enabled }
}
