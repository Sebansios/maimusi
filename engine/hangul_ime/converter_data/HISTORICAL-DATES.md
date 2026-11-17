# Historical date contract and sources

Year labels and dates are different operations. A Korean or Chinese reign year
can be mapped to its conventional Western year label. Its historical lunar month
and day cannot be copied into a Gregorian date. Built-in Korean and Chinese
historical eras therefore accept year-only inputs and reject month/day inputs.
Gregorian dates do not produce invented Korean/Chinese historical lunar dates.
Use explicit `음력 YYYY년 M월 D일` for the optional Korean lunar calendar backend.
That backend's supported range and calendar conventions still apply; it is not
an authority for other countries' historical calendars.

Korean reigns normally count year one in the year following accession. Taejo,
Sejo, Jungjong and Injo count accession as year one; Sunjong's published chronology
also labels 1907 year one. `성종5년` is 1474; `성종즉위년` is 1469. Numeric year zero
is invalid. End years are inclusive conventional year labels, not inferred exact
Gregorian accession dates. Sources:

- [National Institute of Korean History, chronology conventions](https://sillok.history.go.kr/intro/intro.do)
- [Seongjong year 5, 1474](https://sillok.history.go.kr/id/kia_10506003_001)
- [Taejong year 1, 1401](https://sillok.history.go.kr/popup/haejae.do?id=kca)
- [Gwanghae accession year, 1608](https://sillok.history.go.kr/id/kob_10002001_005)
- [Sunjong year 1, 1907](https://contents.history.go.kr/mobile/kc/view.do?levelId=kc_i403220)
- [Palace Museum, Ming and Qing chronology](https://www.dpm.org.cn/court/lineages.html)

Modern Japanese era dates enforce exact Gregorian start/end dates. Meiji dates
before 1873 are rejected because Japan had not yet adopted the Gregorian calendar.
ROC/Minguo is treated as Gregorian. Reiwa and Minguo are open-ended arithmetic era
labels, not predictions about future governments.

- [Imperial Household Agency chronology](https://www.kunaicho.go.jp/kunaicho/kunaicho/kunaicho-nenpyo.html)
- [National Diet Library, Gregorian adoption in 1873](https://www.ndl.go.jp/koyomi/chapter1/s2.html)

`DateConverter(reference_date=None)` takes a fresh Asia/Seoul date on every
conversion request, and snapshots it once for that request. An explicit reference
date remains fixed. Weeks start on Monday; an unqualified weekday refers to the
current week (including past weekdays). Date overflow, invalid years, nonexistent
leap months and invalid days produce no date candidates.
