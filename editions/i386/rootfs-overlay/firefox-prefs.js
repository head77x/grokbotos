// Grok Bot OS i386 defaults (lockPref = user cannot change in about:config)
pref("browser.startup.homepage", "file:///usr/share/grokbot/splash/index.html");
pref("browser.startup.page", 1);
pref("browser.aboutwelcome.enabled", false);
pref("browser.shell.checkDefaultBrowser", false);
pref("datareporting.policy.dataSubmissionEnabled", false);
pref("toolkit.telemetry.enabled", false);
pref("browser.tabs.warnOnClose", false);
pref("browser.sessionstore.resume_from_crash", false);
// 2GB RAM: fewer content processes, smaller caches
pref("dom.ipc.processCount", 2);
pref("browser.cache.memory.capacity", 32768);
pref("browser.sessionhistory.max_total_viewers", 0);
pref("intl.locale.requested", "ko,en-US");
pref("intl.accept_languages", "ko-KR, ko, en-US, en");
