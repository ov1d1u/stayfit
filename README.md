# StayFit for Home Assistant

StayFit is a custom Home Assistant integration for monitoring a Stay Fit Gym
account. It communicates with the same cloud API as the official Android app.

## Entities

Each configured account creates one Home Assistant device with four entities:

- **Subscription active**
- **Active subscription freeze**
- **Subscription expire date**
- **Subscription type**

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
Membership data is refreshed once per hour.

## Disclaimer

This project is an independent integration and is not affiliated with Stay Fit
Gym. It uses an undocumented cloud API that may change without notice.

