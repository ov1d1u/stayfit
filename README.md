# StayFit for Home Assistant

StayFit is a custom Home Assistant integration for monitoring a Stay Fit Gym
account. It communicates with the same cloud API as the official Android app.

## Entities

Each configured account creates one Home Assistant device with twelve entities:

- **Subscription active**
- **Active subscription freeze**
- **Subscription expire date**
- **Subscription type**
- **Available freeze days** — the primary subscription's maximum freeze days
  minus used freeze days, never below zero. The value is unknown when StayFit
  does not provide valid allowance data. Remaining freeze-use limits and other
  eligibility rules still apply when creating a freeze.
- **Last gym check-in** — timestamp of the newest check-in, with the club name
  exposed as an attribute.
- **Check-ins in the last 30 days**
- **Next recurring payment date**
- **Active penalties**
- **Penalties remaining** — the primary subscription's penalty limit minus its
  active penalties, never below zero.
- **Unread app messages**
- **Guest-pass vouchers available**

When an account contains several memberships, the integration selects the
active membership with the latest expiration date. If none is active, it uses
a currently suspended membership, the nearest future membership, or the most
recently expired membership, in that order.

## Installation

### HACS custom repository

1. In HACS, add this repository as a custom repository of type **Integration**.
2. Install **StayFit**.
3. Restart Home Assistant.

### Manual installation

Copy `custom_components/stayfit` into the `custom_components` directory in your
Home Assistant configuration, then restart Home Assistant.

## Configuration

Go to **Settings → Devices & services → Add integration**, search for
**StayFit**, and enter the email address and PIN used by your StayFit account.

The password/PIN is only used during authentication and is not retained in the
Home Assistant config entry. Multiple distinct StayFit accounts can be added.
Membership, activity, and inbox data are refreshed once per hour.

## Freeze and unfreeze actions

Two actions are available in Home Assistant's **Tools → Actions** (called
**Developer Tools → Actions** on older versions). Select a StayFit account for
each call; the account is always required, even if only one is configured.

`stayfit.freeze_subscription` creates a personal freeze (`reason=2` in the
official app). Set `days` to a positive whole number and optionally provide a
`start_date` in `YYYY-MM-DD` format. If omitted, the start date is today in Home
Assistant's configured time zone. StayFit's remaining day allowance, use limit,
advance-notice/backdating rules, and existing freezes are checked before the
request. Recurring subscription freezes must start today.

```yaml
action: stayfit.freeze_subscription
data:
  config_entry_id: "YOUR_STAYFIT_CONFIG_ENTRY_ID"
  days: 7
  start_date: "2026-11-01"
```

`stayfit.unfreeze_subscription` stops the primary subscription's single active
freeze when StayFit permits it to be stopped. An optional `freeze_id` can select
an active or scheduled freeze. Stopping a freeze takes effect immediately and
may change the subscription's expiration date. Medical freezes remain subject
to StayFit's stop permission; contact reception when the app does not allow it.

```yaml
action: stayfit.unfreeze_subscription
data:
  config_entry_id: "YOUR_STAYFIT_CONFIG_ENTRY_ID"
```

Both actions accept an optional `subscription_id` to operate on another
subscription belonging to the selected account. Otherwise they use the same
primary subscription as the entities. The **Subscription type** entity's
attributes expose its `subscription_id`. **Active subscription freeze** exposes
a `freezes` list with `freeze_id`, `date_start`, `date_end`, `days`, and
`can_stop`. Inspect these attributes in **Tools → States**. IDs for other
subscriptions can be obtained from your account's StayFit API data.

To cancel a scheduled freeze, supply its subscription and freeze IDs:

```yaml
action: stayfit.unfreeze_subscription
data:
  config_entry_id: "YOUR_STAYFIT_CONFIG_ENTRY_ID"
  subscription_id: "SUBSCRIPTION_ID"
  freeze_id: "FREEZE_ID"
```

Actions refresh membership data before validation and after a confirmed change,
so the sensors update immediately. Changes for one account run sequentially;
different accounts remain independent. If a response is lost or times out,
the action reports that its outcome is uncertain and does not retry the write.
Check the StayFit app before retrying. If the change succeeds but the following
refresh fails, the error explicitly says the change was already confirmed.

## Disclaimer

This project is an independent integration and is not affiliated with Stay Fit
Gym. It uses an undocumented cloud API that may change without notice.

