import { ref, computed } from 'vue'
import en from './en'
import zh from './zh'

export type Locale = 'en' | 'zh'
type Messages = typeof en

const LOCALE_KEY = 'echome_locale'

const messages: Record<Locale, Messages> = { en, zh }

const currentLocale = ref<Locale>(
  (localStorage.getItem(LOCALE_KEY) as Locale) || 'zh'
)

export function useI18n() {
  function t(key: string): string {
    const msg = messages[currentLocale.value]
    return (msg as Record<string, string>)[key] || key
  }

  function setLocale(locale: Locale): void {
    currentLocale.value = locale
    localStorage.setItem(LOCALE_KEY, locale)
  }

  const locale = computed(() => currentLocale.value)

  return { t, locale, setLocale }
}
