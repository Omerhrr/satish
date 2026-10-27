/**
 * Satish in your language. A small built-in translator (no extra library):
 * t("key") returns the text in the chosen language, falling back to English.
 * The choice is also sent to Satish AI so it answers in the same language.
 *
 * Nigerian languages first (Hausa, Yoruba, Igbo, Pidgin), then widely used
 * African and world languages. Translations of the main screens; anything
 * not yet translated shows in English. Native speakers should review these.
 */

export const LANGUAGES = [
  { code: "en", name: "English" },
  { code: "pcm", name: "Naijá (Pidgin)" },
  { code: "ha", name: "Hausa" },
  { code: "yo", name: "Yorùbá" },
  { code: "ig", name: "Igbo" },
  { code: "fr", name: "Français" },
  { code: "ar", name: "العربية", rtl: true },
  { code: "sw", name: "Kiswahili" },
  { code: "pt", name: "Português" },
  { code: "es", name: "Español" },
  { code: "am", name: "አማርኛ" },
  { code: "zu", name: "isiZulu" },
] as const;

export type Lang = (typeof LANGUAGES)[number]["code"];

type Dict = Record<string, string>;

const en: Dict = {
  "nav.wallet": "Wallet",
  "nav.ai": "Satish AI",
  "tab.home": "Home",
  "tab.history": "History",
  "tab.activity": "Activity",
  "tab.contacts": "Address book",
  "tab.settings": "Settings",
  "tab.ask": "Ask",
  "tab.automations": "Automations",
  "tab.credits": "Credits",
  "tab.connect": "Connect",
  "w.savings": "Bitcoin savings",
  "w.savingsTest": "Bitcoin savings (test)",
  "w.show": "Show",
  "w.hide": "Hide",
  "w.hidden": "Balance hidden",
  "w.receive": "Receive",
  "w.send": "Send",
  "w.buy": "Buy bitcoin",
  "w.request": "Request",
  "w.updating": "Updating…",
  "w.tapRefresh": "Tap to refresh",
  "w.recent": "Recent",
  "w.seeAll": "See all",
  "w.nothingYet": "Nothing yet. Tap Receive to get your address, or share your username.",
  "w.received": "Received",
  "w.sent": "Sent",
  "w.waiting": "Waiting to confirm",
  "set.language": "Language and money",
  "set.languageRow": "Language",
  "set.currencyRow": "Show amounts in",
  "ai.title": "Ask Satish AI",
  "ai.sub": "Research, price comparisons and written reports with sources. It takes TK from your balance only for what it actually uses.",
  "ai.need": "What do you need?",
  "ai.placeholder": "e.g. Compare prices of a 50kg bag of rice in Kaduna markets and make me a PDF report",
  "ai.go": "Ask Satish",
  "ai.tasks": "Tasks",
  "ai.clear": "Clear finished",
  "ai.out": "You're out of TK.",
  "ai.buy": "Buy TK",
  "ai.working": "Working on it…",
  "ai.sentChat": "✓ Sent to your Telegram chat with Satish, including any files.",
  "cr.title": "Credits",
  "cr.yours": "Your credits",
  "cr.buy": "Buy TK",
  "cr.howMuch": "How much TK?",
  "cr.continue": "Continue to payment",
  "amt.yourMoney": "sats or your money",
};

const T: Record<Lang, Dict> = {
  en,
  pcm: {
    "nav.wallet": "Wallet", "nav.ai": "Satish AI", "tab.home": "Home", "tab.history": "Wetin don happen", "tab.activity": "Activity",
    "tab.contacts": "Contacts", "tab.settings": "Settings", "tab.ask": "Ask", "tab.credits": "Credits",
    "w.savings": "Your bitcoin", "w.savingsTest": "Your bitcoin (test)", "w.show": "Show am", "w.hide": "Hide am", "w.hidden": "Balance dey hide",
    "w.receive": "Collect", "w.send": "Send", "w.buy": "Buy bitcoin", "w.request": "Ask for money", "w.updating": "E dey update…",
    "w.tapRefresh": "Touch am to refresh", "w.recent": "Latest", "w.seeAll": "See everything",
    "w.nothingYet": "Nothing never land. Touch Collect to see your address, or share your username.",
    "w.received": "Collect", "w.sent": "Send", "w.waiting": "E dey wait to confirm",
    "set.language": "Language and money", "set.languageRow": "Language", "set.currencyRow": "Show money for",
    "ai.title": "Ask Satish AI", "ai.sub": "Research, compare price, write report with source. E go only collect TK for wetin e use.",
    "ai.need": "Wetin you need?", "ai.placeholder": "e.g. Compare price of 50kg rice for Kaduna market, make PDF for me",
    "ai.go": "Ask Satish", "ai.tasks": "Tasks", "ai.clear": "Clear the finished ones", "ai.out": "Your TK don finish.", "ai.buy": "Buy TK",
    "ai.working": "E dey work am…", "ai.sentChat": "✓ We don send am to your Telegram chat with Satish, with any file.",
    "cr.title": "Credits", "cr.yours": "Your credits", "cr.buy": "Buy TK", "cr.howMuch": "How much TK you want?", "cr.continue": "Go pay",
    "amt.yourMoney": "sats or naira/dollar",
  },
  ha: {
    "nav.wallet": "Walat", "nav.ai": "Satish AI", "tab.home": "Gida", "tab.history": "Tarihi", "tab.activity": "Ayyuka",
    "tab.contacts": "Lambobin sadarwa", "tab.settings": "Saituna", "tab.ask": "Tambaya", "tab.automations": "Aiki da kai", "tab.credits": "Kiredit", "tab.connect": "Haɗa",
    "w.savings": "Ajiyar bitcoin", "w.savingsTest": "Ajiyar bitcoin (gwaji)", "w.show": "Nuna", "w.hide": "Ɓoye", "w.hidden": "An ɓoye ma'auni",
    "w.receive": "Karɓa", "w.send": "Aika", "w.buy": "Sayi bitcoin", "w.request": "Nemi kuɗi", "w.updating": "Ana sabuntawa…",
    "w.tapRefresh": "Taɓa don sabuntawa", "w.recent": "Na baya-bayan nan", "w.seeAll": "Duba duka",
    "w.nothingYet": "Babu komai tukuna. Taɓa Karɓa don samun adireshinka, ko raba sunan mai amfani.",
    "w.received": "An karɓa", "w.sent": "An aika", "w.waiting": "Ana jiran tabbatarwa",
    "set.language": "Harshe da kuɗi", "set.languageRow": "Harshe", "set.currencyRow": "Nuna kuɗi a",
    "ai.title": "Tambayi Satish AI", "ai.sub": "Bincike, kwatanta farashi da rahotanni masu tushe. Yana cire TK ne kawai daidai da abin da ya yi amfani da shi.",
    "ai.need": "Me kake bukata?", "ai.placeholder": "misali: Kwatanta farashin buhun shinkafa 50kg a kasuwannin Kaduna ka yi min rahoton PDF",
    "ai.go": "Tambayi Satish", "ai.tasks": "Ayyuka", "ai.clear": "Share waɗanda suka gama", "ai.out": "TK ɗinka ya ƙare.", "ai.buy": "Sayi TK",
    "ai.working": "Ana aiki…", "ai.sentChat": "✓ An aika zuwa hirarka ta Telegram da Satish, tare da fayiloli.",
    "cr.title": "Kiredit", "cr.yours": "Kiredit ɗinka", "cr.buy": "Sayi TK", "cr.howMuch": "TK nawa?", "cr.continue": "Ci gaba zuwa biya",
    "amt.yourMoney": "sats ko kuɗinka",
  },
  yo: {
    "nav.wallet": "Àpò owó", "nav.ai": "Satish AI", "tab.home": "Ilé", "tab.history": "Ìtàn", "tab.activity": "Ìṣe",
    "tab.contacts": "Àwọn olùbásọ̀rọ̀", "tab.settings": "Ètò", "tab.ask": "Béèrè", "tab.credits": "Kírẹ́dìtì",
    "w.savings": "Ìfowópamọ́ bitcoin", "w.savingsTest": "Ìfowópamọ́ bitcoin (ìdánwò)", "w.show": "Fihàn", "w.hide": "Fi pamọ́", "w.hidden": "A ti fi iye owó pamọ́",
    "w.receive": "Gbà", "w.send": "Fi ránṣẹ́", "w.buy": "Ra bitcoin", "w.request": "Béèrè owó", "w.updating": "Ń ṣe àtúnṣe…",
    "w.tapRefresh": "Tẹ̀ láti tún un ṣe", "w.recent": "Àìpẹ́", "w.seeAll": "Wo gbogbo rẹ̀",
    "w.nothingYet": "Kò sí nǹkan kan síbẹ̀. Tẹ Gbà láti rí àdírẹ́sì rẹ, tàbí pín orúkọ rẹ.",
    "w.received": "Ó dé", "w.sent": "A fi ránṣẹ́", "w.waiting": "Ń dúró de ìjẹ́rìísí",
    "set.language": "Èdè àti owó", "set.languageRow": "Èdè", "set.currencyRow": "Fi owó hàn ní",
    "ai.title": "Béèrè lọ́wọ́ Satish AI", "ai.sub": "Ìwádìí, àfiwé iye owó àti ìròyìn tí ó ní orísun. Ó ń gba TK fún ohun tí ó lò nìkan.",
    "ai.need": "Kí lo nílò?", "ai.placeholder": "àpẹẹrẹ: Fi iye owó àpò ìrẹsì 50kg ní ọjà Kaduna wé ara wọn, kí o sì ṣe PDF fún mi",
    "ai.go": "Béèrè lọ́wọ́ Satish", "ai.tasks": "Iṣẹ́", "ai.clear": "Pa àwọn tí ó ti parí rẹ́", "ai.out": "TK rẹ ti tán.", "ai.buy": "Ra TK",
    "ai.working": "Ó ń ṣiṣẹ́ lórí rẹ̀…", "ai.sentChat": "✓ A ti fi ránṣẹ́ sí ìjíròrò Telegram rẹ pẹ̀lú Satish.",
    "cr.title": "Kírẹ́dìtì", "cr.yours": "Kírẹ́dìtì rẹ", "cr.buy": "Ra TK", "cr.howMuch": "TK mélòó?", "cr.continue": "Tẹ̀síwájú sí ìsanwó",
    "amt.yourMoney": "sats tàbí owó rẹ",
  },
  ig: {
    "nav.wallet": "Obere akpa ego", "nav.ai": "Satish AI", "tab.home": "Ụlọ", "tab.history": "Akụkọ", "tab.activity": "Ọrụ",
    "tab.contacts": "Ndị kọntaktị", "tab.settings": "Ntọala", "tab.ask": "Jụọ", "tab.credits": "Kredit",
    "w.savings": "Nchekwa bitcoin", "w.savingsTest": "Nchekwa bitcoin (nnwale)", "w.show": "Gosi", "w.hide": "Zoo", "w.hidden": "Ezoro ego dị",
    "w.receive": "Nata", "w.send": "Zipu", "w.buy": "Zụta bitcoin", "w.request": "Rịọ ego", "w.updating": "Na-emelite…",
    "w.tapRefresh": "Pịa ka ọ mee ọhụrụ", "w.recent": "Nke ọhụrụ", "w.seeAll": "Hụ ha niile",
    "w.nothingYet": "Ọ dịbeghị ihe ọ bụla. Pịa Nata ka ị hụ adreesị gị, ma ọ bụ kesaa aha gị.",
    "w.received": "Natara", "w.sent": "Zipụrụ", "w.waiting": "Na-eche nkwenye",
    "set.language": "Asụsụ na ego", "set.languageRow": "Asụsụ", "set.currencyRow": "Gosi ego na",
    "ai.title": "Jụọ Satish AI", "ai.sub": "Nchọpụta, ntụnyere ọnụahịa na akụkọ nwere isi mmalite. Ọ na-ewe TK maka ihe o ji mee naanị.",
    "ai.need": "Gịnị ka ị chọrọ?", "ai.placeholder": "dịka: Tụnyere ọnụahịa akpa osikapa 50kg n'ahịa Kaduna, mee m PDF",
    "ai.go": "Jụọ Satish", "ai.tasks": "Ọrụ", "ai.clear": "Hichapụ ndị gwụchara", "ai.out": "TK gị agwụla.", "ai.buy": "Zụta TK",
    "ai.working": "Ọ na-arụ ya…", "ai.sentChat": "✓ Ezigara ya na mkparịta ụka Telegram gị na Satish.",
    "cr.title": "Kredit", "cr.yours": "Kredit gị", "cr.buy": "Zụta TK", "cr.howMuch": "TK ole?", "cr.continue": "Gaa n'ịkwụ ụgwọ",
    "amt.yourMoney": "sats ma ọ bụ ego gị",
  },
  fr: {
    "nav.wallet": "Portefeuille", "nav.ai": "Satish IA", "tab.home": "Accueil", "tab.history": "Historique", "tab.activity": "Activité",
    "tab.contacts": "Carnet d'adresses", "tab.settings": "Réglages", "tab.ask": "Demander", "tab.automations": "Automatisations", "tab.credits": "Crédits", "tab.connect": "Connecter",
    "w.savings": "Épargne bitcoin", "w.savingsTest": "Épargne bitcoin (test)", "w.show": "Afficher", "w.hide": "Masquer", "w.hidden": "Solde masqué",
    "w.receive": "Recevoir", "w.send": "Envoyer", "w.buy": "Acheter du bitcoin", "w.request": "Demander", "w.updating": "Mise à jour…",
    "w.tapRefresh": "Touchez pour actualiser", "w.recent": "Récent", "w.seeAll": "Tout voir",
    "w.nothingYet": "Rien pour l'instant. Touchez Recevoir pour obtenir votre adresse, ou partagez votre nom d'utilisateur.",
    "w.received": "Reçu", "w.sent": "Envoyé", "w.waiting": "En attente de confirmation",
    "set.language": "Langue et devise", "set.languageRow": "Langue", "set.currencyRow": "Afficher les montants en",
    "ai.title": "Demander à Satish IA", "ai.sub": "Recherches, comparaisons de prix et rapports sourcés. Seuls les TK réellement utilisés sont prélevés.",
    "ai.need": "De quoi avez-vous besoin ?", "ai.placeholder": "ex. Comparer le prix d'un sac de riz de 50 kg sur les marchés et en faire un rapport PDF",
    "ai.go": "Demander à Satish", "ai.tasks": "Tâches", "ai.clear": "Effacer les terminées", "ai.out": "Vous n'avez plus de TK.", "ai.buy": "Acheter des TK",
    "ai.working": "En cours…", "ai.sentChat": "✓ Envoyé dans votre discussion Telegram avec Satish, fichiers compris.",
    "cr.title": "Crédits", "cr.yours": "Vos crédits", "cr.buy": "Acheter des TK", "cr.howMuch": "Combien de TK ?", "cr.continue": "Continuer vers le paiement",
    "amt.yourMoney": "sats ou votre monnaie",
  },
  ar: {
    "nav.wallet": "المحفظة", "nav.ai": "ساتيش AI", "tab.home": "الرئيسية", "tab.history": "السجل", "tab.activity": "النشاط",
    "tab.contacts": "جهات الاتصال", "tab.settings": "الإعدادات", "tab.ask": "اسأل", "tab.automations": "المهام التلقائية", "tab.credits": "الرصيد", "tab.connect": "ربط",
    "w.savings": "مدخرات البيتكوين", "w.savingsTest": "مدخرات البيتكوين (تجريبي)", "w.show": "إظهار", "w.hide": "إخفاء", "w.hidden": "الرصيد مخفي",
    "w.receive": "استلام", "w.send": "إرسال", "w.buy": "شراء بيتكوين", "w.request": "طلب", "w.updating": "جارٍ التحديث…",
    "w.tapRefresh": "اضغط للتحديث", "w.recent": "الأحدث", "w.seeAll": "عرض الكل",
    "w.nothingYet": "لا شيء بعد. اضغط استلام للحصول على عنوانك أو شارك اسم المستخدم.",
    "w.received": "مستلم", "w.sent": "مرسل", "w.waiting": "بانتظار التأكيد",
    "set.language": "اللغة والعملة", "set.languageRow": "اللغة", "set.currencyRow": "عرض المبالغ بـ",
    "ai.title": "اسأل ساتيش AI", "ai.sub": "أبحاث ومقارنة أسعار وتقارير موثقة بالمصادر. يُخصم من رصيدك ما يُستخدم فقط.",
    "ai.need": "ماذا تحتاج؟", "ai.placeholder": "مثال: قارن أسعار كيس أرز 50 كغ في الأسواق واصنع لي تقرير PDF",
    "ai.go": "اسأل ساتيش", "ai.tasks": "المهام", "ai.clear": "مسح المهام المنتهية", "ai.out": "نفد رصيد TK.", "ai.buy": "شراء TK",
    "ai.working": "جارٍ العمل…", "ai.sentChat": "✓ أُرسل إلى محادثتك في تيليجرام مع ساتيش مع الملفات.",
    "cr.title": "الرصيد", "cr.yours": "رصيدك", "cr.buy": "شراء TK", "cr.howMuch": "كم TK؟", "cr.continue": "متابعة الدفع",
    "amt.yourMoney": "ساتوشي أو عملتك",
  },
  sw: {
    "nav.wallet": "Pochi", "nav.ai": "Satish AI", "tab.home": "Nyumbani", "tab.history": "Historia", "tab.activity": "Shughuli",
    "tab.contacts": "Anwani", "tab.settings": "Mipangilio", "tab.ask": "Uliza", "tab.credits": "Salio",
    "w.savings": "Akiba ya bitcoin", "w.savingsTest": "Akiba ya bitcoin (majaribio)", "w.show": "Onyesha", "w.hide": "Ficha", "w.hidden": "Salio limefichwa",
    "w.receive": "Pokea", "w.send": "Tuma", "w.buy": "Nunua bitcoin", "w.request": "Omba", "w.updating": "Inasasisha…",
    "w.tapRefresh": "Gusa kusasisha", "w.recent": "Za karibuni", "w.seeAll": "Ona zote",
    "w.nothingYet": "Bado hakuna kitu. Gusa Pokea kupata anwani yako, au shiriki jina lako la mtumiaji.",
    "w.received": "Imepokelewa", "w.sent": "Imetumwa", "w.waiting": "Inasubiri uthibitisho",
    "set.language": "Lugha na pesa", "set.languageRow": "Lugha", "set.currencyRow": "Onyesha kiasi kwa",
    "ai.title": "Uliza Satish AI", "ai.sub": "Utafiti, kulinganisha bei na ripoti zenye vyanzo. Hutoza TK kwa kile kinachotumika tu.",
    "ai.need": "Unahitaji nini?", "ai.placeholder": "mf. Linganisha bei ya gunia la mchele kilo 50 sokoni na uniandalie ripoti ya PDF",
    "ai.go": "Uliza Satish", "ai.tasks": "Kazi", "ai.clear": "Futa zilizokamilika", "ai.out": "TK zako zimeisha.", "ai.buy": "Nunua TK",
    "ai.working": "Inafanyia kazi…", "ai.sentChat": "✓ Imetumwa kwenye mazungumzo yako ya Telegram na Satish.",
    "cr.title": "Salio", "cr.yours": "Salio lako", "cr.buy": "Nunua TK", "cr.howMuch": "TK ngapi?", "cr.continue": "Endelea kulipa",
    "amt.yourMoney": "sats au pesa yako",
  },
  pt: {
    "nav.wallet": "Carteira", "nav.ai": "Satish IA", "tab.home": "Início", "tab.history": "Histórico", "tab.activity": "Atividade",
    "tab.contacts": "Contatos", "tab.settings": "Definições", "tab.ask": "Perguntar", "tab.credits": "Créditos",
    "w.savings": "Poupança em bitcoin", "w.savingsTest": "Poupança em bitcoin (teste)", "w.show": "Mostrar", "w.hide": "Ocultar", "w.hidden": "Saldo oculto",
    "w.receive": "Receber", "w.send": "Enviar", "w.buy": "Comprar bitcoin", "w.request": "Pedir", "w.updating": "A atualizar…",
    "w.tapRefresh": "Toque para atualizar", "w.recent": "Recentes", "w.seeAll": "Ver tudo",
    "w.nothingYet": "Ainda nada. Toque em Receber para obter o seu endereço ou partilhe o seu nome de utilizador.",
    "w.received": "Recebido", "w.sent": "Enviado", "w.waiting": "A aguardar confirmação",
    "set.language": "Idioma e moeda", "set.languageRow": "Idioma", "set.currencyRow": "Mostrar valores em",
    "ai.title": "Pergunte à Satish IA", "ai.sub": "Pesquisa, comparação de preços e relatórios com fontes. Só cobra os TK que usar.",
    "ai.need": "Do que precisa?", "ai.placeholder": "ex. Compare o preço de um saco de arroz de 50 kg nos mercados e faça um PDF",
    "ai.go": "Perguntar", "ai.tasks": "Tarefas", "ai.clear": "Limpar concluídas", "ai.out": "Ficou sem TK.", "ai.buy": "Comprar TK",
    "ai.working": "A trabalhar…", "ai.sentChat": "✓ Enviado para a sua conversa do Telegram com a Satish.",
    "cr.title": "Créditos", "cr.yours": "Os seus créditos", "cr.buy": "Comprar TK", "cr.howMuch": "Quantos TK?", "cr.continue": "Continuar para pagamento",
    "amt.yourMoney": "sats ou a sua moeda",
  },
  es: {
    "nav.wallet": "Billetera", "nav.ai": "Satish IA", "tab.home": "Inicio", "tab.history": "Historial", "tab.activity": "Actividad",
    "tab.contacts": "Contactos", "tab.settings": "Ajustes", "tab.ask": "Preguntar", "tab.automations": "Automatizaciones", "tab.credits": "Créditos", "tab.connect": "Conectar",
    "w.savings": "Ahorro en bitcoin", "w.savingsTest": "Ahorro en bitcoin (prueba)", "w.show": "Mostrar", "w.hide": "Ocultar", "w.hidden": "Saldo oculto",
    "w.receive": "Recibir", "w.send": "Enviar", "w.buy": "Comprar bitcoin", "w.request": "Cobrar", "w.updating": "Actualizando…",
    "w.tapRefresh": "Toca para actualizar", "w.recent": "Reciente", "w.seeAll": "Ver todo",
    "w.nothingYet": "Nada todavía. Toca Recibir para ver tu dirección o comparte tu nombre de usuario.",
    "w.received": "Recibido", "w.sent": "Enviado", "w.waiting": "Esperando confirmación",
    "set.language": "Idioma y moneda", "set.languageRow": "Idioma", "set.currencyRow": "Mostrar importes en",
    "ai.title": "Pregunta a Satish IA", "ai.sub": "Investigación, comparación de precios e informes con fuentes. Solo cobra los TK que usa.",
    "ai.need": "¿Qué necesitas?", "ai.placeholder": "ej. Compara el precio de un saco de arroz de 50 kg en los mercados y hazme un PDF",
    "ai.go": "Preguntar", "ai.tasks": "Tareas", "ai.clear": "Borrar terminadas", "ai.out": "Te quedaste sin TK.", "ai.buy": "Comprar TK",
    "ai.working": "Trabajando…", "ai.sentChat": "✓ Enviado a tu chat de Telegram con Satish, con los archivos.",
    "cr.title": "Créditos", "cr.yours": "Tus créditos", "cr.buy": "Comprar TK", "cr.howMuch": "¿Cuántos TK?", "cr.continue": "Continuar al pago",
    "amt.yourMoney": "sats o tu moneda",
  },
  am: {
    "nav.wallet": "ቦርሳ", "nav.ai": "ሳቲሽ AI", "tab.home": "መነሻ", "tab.history": "ታሪክ", "tab.settings": "ቅንብሮች", "tab.ask": "ጠይቅ",
    "w.receive": "ተቀበል", "w.send": "ላክ", "w.buy": "ቢትኮይን ግዛ", "w.request": "ጠይቅ", "w.recent": "የቅርብ ጊዜ",
    "set.language": "ቋንቋ እና ገንዘብ", "set.languageRow": "ቋንቋ", "set.currencyRow": "መጠን አሳይ በ",
    "ai.title": "ሳቲሽ AIን ጠይቅ", "ai.need": "ምን ያስፈልግዎታል?", "ai.go": "ጠይቅ", "ai.tasks": "ተግባሮች",
  },
  zu: {
    "nav.wallet": "Isikhwama", "tab.home": "Ekhaya", "tab.history": "Umlando", "tab.settings": "Izilungiselelo", "tab.ask": "Buza",
    "w.receive": "Thola", "w.send": "Thumela", "w.buy": "Thenga i-bitcoin", "w.request": "Cela", "w.recent": "Okwakamuva",
    "set.language": "Ulimi nemali", "set.languageRow": "Ulimi", "set.currencyRow": "Bonisa amanani ku-",
    "ai.title": "Buza u-Satish AI", "ai.need": "Udingani?", "ai.go": "Buza", "ai.tasks": "Imisebenzi",
  },
};

const LANG_KEY = "satish_lang";

function detect(): Lang {
  try {
    const saved = localStorage.getItem(LANG_KEY) as Lang | null;
    if (saved && saved in T) return saved;
  } catch {
    /* ignore */
  }
  const tg = (globalThis as any).Telegram?.WebApp?.initDataUnsafe?.user?.language_code as string | undefined;
  for (const raw of [tg, ...(navigator.languages || [navigator.language])]) {
    const base = String(raw || "").toLowerCase().split("-")[0] as Lang;
    if (base && base in T) return base;
  }
  return "en";
}

const lang = ref<Lang>(typeof window !== "undefined" ? detect() : "en");

function applyDir(l: Lang) {
  if (typeof document === "undefined") return;
  const meta = LANGUAGES.find((x) => x.code === l);
  document.documentElement.lang = l;
  document.documentElement.dir = meta && "rtl" in meta && meta.rtl ? "rtl" : "ltr";
}
if (typeof window !== "undefined") applyDir(lang.value);

export function useI18n() {
  function t(key: string, vars?: Record<string, string | number>): string {
    let s = T[lang.value]?.[key] ?? en[key] ?? key;
    if (vars) for (const [k, v] of Object.entries(vars)) s = s.replace(`{${k}}`, String(v));
    return s;
  }
  function setLang(l: Lang) {
    lang.value = l;
    applyDir(l);
    try {
      localStorage.setItem(LANG_KEY, l);
    } catch {
      /* ignore */
    }
  }
  /** English name of the language, for telling Satish AI how to answer. */
  const languageName = computed(() => {
    const names: Record<Lang, string> = {
      en: "English", pcm: "Nigerian Pidgin", ha: "Hausa", yo: "Yoruba", ig: "Igbo", fr: "French", ar: "Arabic",
      sw: "Swahili", pt: "Portuguese", es: "Spanish", am: "Amharic", zu: "Zulu",
    };
    return names[lang.value];
  });
  return { t, lang, setLang, languageName, LANGUAGES };
}
