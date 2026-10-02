from tripwire.nlp.filing_lead import filing_lead


def test_filing_lead_uses_press_release_without_headings():
    exhibit = (
        "Exhibit 99.1\nPRESS RELEASE\n"
        "Item 2.02 Results of Operations and Financial Condition\n"
        "Acme Bank reports third-quarter net loss of $1.2 billion as credit costs rise sharply.\n"
        "Provisions for loan losses tripled from a year earlier, the bank said on Tuesday.\n"
        "A third sentence that should not be part of the lead at all, being the third one here.\n"
    )
    lead = filing_lead("", exhibit)
    assert lead.startswith("Acme Bank reports third-quarter net loss")
    assert "Item 2.02" not in lead and "Provisions for loan losses tripled" in lead
    assert "third sentence" not in lead


def test_contact_blocks_are_skipped():
    exhibit = ("CONTACTS MEDIA: Anne Pace (631) 338-3268 anne.pace@example.com INVESTORS: Bryan\n"
               "The bank reported record quarterly earnings driven by higher net interest income.\n")
    assert filing_lead("", exhibit).startswith("The bank reported record quarterly earnings")


def test_filing_lead_falls_back_to_main_text():
    main = "UNITED STATES SECURITIES AND EXCHANGE COMMISSION FORM 8-K\nItem 5.02 Departure of Officers\n" \
           "On October 1, the Board appointed Jane Doe as Chief Financial Officer, effective immediately."
    assert filing_lead(main, "").startswith("On October 1, the Board appointed Jane Doe")
