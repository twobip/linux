// SPDX-License-Identifier: GPL-2.0 OR BSD-2-Clause
/* Included by t6040-usb2.c to exercise the real ownership paths. */
#include <kunit/device.h>
#include <kunit/test.h>

struct t6040_test {
	struct t6040_usb2_phy tphy;
	struct phy dp;
	struct phy usb3;
	int init_ret;
	int off_ret;
	unsigned int init_calls;
	unsigned int setup_calls;
	unsigned int sleep_calls;
	unsigned int off_calls;
	unsigned int usb_calls;
	unsigned int pipe_calls;
	unsigned int seq_calls;
	unsigned int fail_at;
};

static int t6040_test_dp_init(struct t6040_usb2_phy *tphy, bool flip)
{
	struct t6040_test *ctx = container_of(tphy, struct t6040_test, tphy);

	ctx->init_calls++;
	return ctx->init_ret;
}

static void t6040_test_dp_setup(struct t6040_usb2_phy *tphy, bool flip)
{
	struct t6040_test *ctx = container_of(tphy, struct t6040_test, tphy);

	ctx->setup_calls++;
}

static void t6040_test_sleep(struct t6040_usb2_phy *tphy)
{
	struct t6040_test *ctx = container_of(tphy, struct t6040_test, tphy);

	ctx->sleep_calls++;
}

static int t6040_test_rate(struct t6040_usb2_phy *tphy, int idx)
{
	struct t6040_test *ctx = container_of(tphy, struct t6040_test, tphy);

	ctx->off_calls++;
	return ctx->off_ret;
}

static int t6040_test_usb_start(struct t6040_usb2_phy *tphy)
{
	struct t6040_test *ctx = container_of(tphy, struct t6040_test, tphy);

	ctx->usb_calls++;
	tphy->usb3_up = true;
	return 0;
}

static void t6040_test_pipe_switch(struct t6040_usb2_phy *tphy)
{
	struct t6040_test *ctx = container_of(tphy, struct t6040_test, tphy);

	ctx->pipe_calls++;
}

static int t6040_test_init(struct kunit *test)
{
	struct t6040_test *ctx = kunit_kzalloc(test, sizeof(*ctx), GFP_KERNEL);

	KUNIT_ASSERT_NOT_NULL(test, ctx);
	ctx->tphy.dev = kunit_device_register(test, "t6040-phy-test");
	KUNIT_ASSERT_NOT_ERR_OR_NULL(test, ctx->tphy.dev);
	mutex_init(&ctx->tphy.lock);
	ctx->tphy.typec_port = true;
	ctx->tphy.usb3_ok = true;
	ctx->tphy.dp_ok = true;
	ctx->tphy.orientation = TYPEC_ORIENTATION_NORMAL;
	ctx->tphy.dp_rate = -1;
	phy_set_drvdata(&ctx->dp, &ctx->tphy);
	phy_set_drvdata(&ctx->usb3, &ctx->tphy);
	test->priv = ctx;
	kunit_activate_static_stub(test, t6040_dp_phy_init, t6040_test_dp_init);
	kunit_activate_static_stub(test, t6040_dp_mode_setup, t6040_test_dp_setup);
	kunit_activate_static_stub(test, t6040_usb3_sleep, t6040_test_sleep);
	kunit_activate_static_stub(test, t6040_dp_set_rate, t6040_test_rate);
	kunit_activate_static_stub(test, t6040_usb3_start_locked, t6040_test_usb_start);
	kunit_activate_static_stub(test, t6040_usb3_pipe_switch, t6040_test_pipe_switch);
	return 0;
}

static int t6040_test_mux(struct t6040_test *ctx, unsigned long mode, bool hpd)
{
	struct typec_altmode alt = { .svid = USB_TYPEC_DP_SID };
	struct typec_displayport_data data = { .status = hpd ? DP_STATUS_HPD_STATE : 0 };
	struct typec_mux_state state = { .mode = mode };

	if (mode >= TYPEC_DP_STATE_A) {
		state.alt = &alt;
		state.data = &data;
	}
	return t6040_dp_mux_update(&ctx->tphy, &state);
}

static void t6040_test_assignments(struct kunit *test)
{
	struct t6040_test *ctx = test->priv;

	KUNIT_EXPECT_EQ(test, t6040_test_mux(ctx, TYPEC_DP_STATE_D, true), -ENODEV);
	KUNIT_EXPECT_FALSE(test, ctx->tphy.dp_alt);
	KUNIT_EXPECT_EQ(test, t6040_test_mux(ctx, TYPEC_DP_STATE_C, true), 0);
	KUNIT_EXPECT_TRUE(test, apple_t6040_phy_dp_alt(&ctx->dp));
	KUNIT_EXPECT_EQ(test, t6040_test_mux(ctx, TYPEC_DP_STATE_E, true), 0);
	KUNIT_EXPECT_EQ(test, t6040_test_mux(ctx, TYPEC_STATE_USB, false), 0);
	KUNIT_EXPECT_FALSE(test, apple_t6040_phy_dp_alt(&ctx->dp));
}

static void t6040_test_missing_usb3_is_not_hdmi(struct kunit *test)
{
	struct t6040_test *ctx = test->priv;

	ctx->tphy.usb3_ok = false;
	KUNIT_EXPECT_FALSE(test, t6040_dp_only(&ctx->tphy));
	KUNIT_EXPECT_EQ(test, t6040_test_mux(ctx, TYPEC_DP_STATE_C, true), -ENODEV);
	KUNIT_EXPECT_EQ(test, t6040_dp_power_on(&ctx->dp), -ENOLINK);
	KUNIT_EXPECT_EQ(test, ctx->init_calls, 0U);
}

static void t6040_test_requires_assignment(struct kunit *test)
{
	struct t6040_test *ctx = test->priv;

	KUNIT_EXPECT_EQ(test, t6040_dp_power_on(&ctx->dp), -ENOLINK);
	KUNIT_EXPECT_EQ(test, ctx->init_calls, 0U);
	ctx->tphy.typec_port = false;
	KUNIT_EXPECT_EQ(test, t6040_dp_power_on(&ctx->dp), 0);
	KUNIT_EXPECT_TRUE(test, ctx->tphy.dp_up);
}

static void t6040_test_live_usb_is_not_parked(struct kunit *test)
{
	struct t6040_test *ctx = test->priv;

	KUNIT_ASSERT_EQ(test, t6040_test_mux(ctx, TYPEC_DP_STATE_C, true), 0);
	ctx->tphy.usb3_up = true;
	ctx->tphy.pipe_switched = true;
	KUNIT_EXPECT_EQ(test, t6040_dp_power_on(&ctx->dp), -EBUSY);
	KUNIT_EXPECT_TRUE(test, ctx->tphy.usb3_up);
	KUNIT_EXPECT_TRUE(test, ctx->tphy.pipe_switched);
	KUNIT_EXPECT_EQ(test, ctx->init_calls, 0U);
}

static void t6040_test_usb_stays_on_dummy(struct kunit *test)
{
	struct t6040_test *ctx = test->priv;

	KUNIT_ASSERT_EQ(test, t6040_test_mux(ctx, TYPEC_DP_STATE_C, true), 0);
	/* These must return before any MMIO, even before DCP powers DP on. */
	KUNIT_EXPECT_EQ(test, t6040_usb3_power_on(&ctx->usb3), 0);
	KUNIT_EXPECT_EQ(test, t6040_usb3_set_mode(&ctx->usb3, PHY_MODE_USB_HOST, 0), 0);
	KUNIT_EXPECT_FALSE(test, ctx->tphy.usb3_up);
	KUNIT_EXPECT_FALSE(test, ctx->tphy.pipe_switched);
	KUNIT_ASSERT_EQ(test, t6040_dp_power_on(&ctx->dp), 0);
	KUNIT_EXPECT_EQ(test, t6040_usb3_power_off(&ctx->usb3), 0);
	KUNIT_EXPECT_TRUE(test, ctx->tphy.dp_up);
	KUNIT_EXPECT_EQ(test, ctx->sleep_calls, 0U);
}

static void t6040_test_disconnect_drains(struct kunit *test)
{
	struct t6040_test *ctx = test->priv;

	KUNIT_ASSERT_EQ(test, t6040_test_mux(ctx, TYPEC_DP_STATE_C, true), 0);
	KUNIT_ASSERT_EQ(test, t6040_dp_power_on(&ctx->dp), 0);
	KUNIT_EXPECT_EQ(test, t6040_test_mux(ctx, TYPEC_DP_STATE_C, false), 0);
	KUNIT_EXPECT_FALSE(test, apple_t6040_phy_dp_alt(&ctx->dp));
	KUNIT_EXPECT_TRUE(test, ctx->tphy.dp_up);
	KUNIT_EXPECT_EQ(test, t6040_test_mux(ctx, TYPEC_STATE_SAFE, false), -ETIMEDOUT);
	KUNIT_EXPECT_EQ(test, t6040_test_mux(ctx, TYPEC_DP_STATE_C, true), -ETIMEDOUT);
	KUNIT_ASSERT_EQ(test, t6040_dp_power_off(&ctx->dp), 0);
	KUNIT_EXPECT_EQ(test, ctx->off_calls, 1U);
	KUNIT_EXPECT_EQ(test, ctx->sleep_calls, 1U);
	KUNIT_EXPECT_FALSE(test, ctx->tphy.dp_up);
	KUNIT_EXPECT_EQ(test, t6040_test_mux(ctx, TYPEC_STATE_USB, false), 0);
	KUNIT_EXPECT_FALSE(test, ctx->tphy.dp_alt);
}

static void t6040_test_usb3_after_dp(struct kunit *test)
{
	struct t6040_test *ctx = test->priv;

	KUNIT_ASSERT_EQ(test, t6040_test_mux(ctx, TYPEC_DP_STATE_C, true), 0);
	KUNIT_ASSERT_EQ(test, t6040_usb3_power_on(&ctx->usb3), 0);
	KUNIT_ASSERT_EQ(test, t6040_dp_power_on(&ctx->dp), 0);
	KUNIT_EXPECT_EQ(test, ctx->usb_calls, 0U);
	/* tipd reports the display gone and stops the USB role before SAFE. */
	KUNIT_ASSERT_EQ(test, t6040_test_mux(ctx, TYPEC_DP_STATE_C, false), 0);
	KUNIT_ASSERT_EQ(test, t6040_usb3_power_off(&ctx->usb3), 0);
	KUNIT_ASSERT_EQ(test, t6040_dp_power_off(&ctx->dp), 0);
	KUNIT_ASSERT_EQ(test, t6040_test_mux(ctx, TYPEC_STATE_USB, false), 0);
	KUNIT_ASSERT_EQ(test, t6040_usb3_power_on(&ctx->usb3), 0);
	KUNIT_EXPECT_TRUE(test, ctx->tphy.usb3_up);
	KUNIT_EXPECT_EQ(test, ctx->usb_calls, 1U);
	KUNIT_ASSERT_EQ(test, t6040_usb3_set_mode(&ctx->usb3, PHY_MODE_USB_HOST, 0), 0);
	KUNIT_EXPECT_TRUE(test, ctx->tphy.pipe_switched);
	KUNIT_EXPECT_EQ(test, ctx->pipe_calls, 1U);
}

static void t6040_test_hpd_low_keeps_dp_lanes(struct kunit *test)
{
	struct t6040_test *ctx = test->priv;

	KUNIT_ASSERT_EQ(test, t6040_test_mux(ctx, TYPEC_DP_STATE_C, true), 0);
	KUNIT_ASSERT_EQ(test, t6040_dp_power_on(&ctx->dp), 0);
	KUNIT_ASSERT_EQ(test, t6040_test_mux(ctx, TYPEC_DP_STATE_C, false), 0);
	KUNIT_ASSERT_EQ(test, t6040_dp_power_off(&ctx->dp), 0);
	/* HPD is not the pin assignment. A sleeping sink still owns the lanes. */
	KUNIT_EXPECT_TRUE(test, ctx->tphy.dp_assigned);
	KUNIT_ASSERT_EQ(test, t6040_usb3_power_on(&ctx->usb3), 0);
	KUNIT_EXPECT_EQ(test, ctx->usb_calls, 0U);
	KUNIT_ASSERT_EQ(test, t6040_test_mux(ctx, TYPEC_STATE_USB, false), 0);
	KUNIT_ASSERT_EQ(test, t6040_usb3_power_on(&ctx->usb3), 0);
	KUNIT_EXPECT_EQ(test, ctx->usb_calls, 1U);
}

static void t6040_test_failed_init(struct kunit *test)
{
	struct t6040_test *ctx = test->priv;

	KUNIT_ASSERT_EQ(test, t6040_test_mux(ctx, TYPEC_DP_STATE_C, true), 0);
	ctx->init_ret = -ETIMEDOUT;
	KUNIT_EXPECT_EQ(test, t6040_dp_power_on(&ctx->dp), -ETIMEDOUT);
	KUNIT_EXPECT_FALSE(test, ctx->tphy.dp_up);
	KUNIT_EXPECT_EQ(test, ctx->setup_calls, 0U);
	KUNIT_EXPECT_EQ(test, ctx->sleep_calls, 1U);
	KUNIT_EXPECT_EQ(test, t6040_test_mux(ctx, TYPEC_STATE_USB, false), 0);
	/* A later assignment may start from a clean block. */
	ctx->init_ret = 0;
	KUNIT_ASSERT_EQ(test, t6040_test_mux(ctx, TYPEC_DP_STATE_C, true), 0);
	KUNIT_EXPECT_EQ(test, t6040_dp_power_on(&ctx->dp), 0);
}

static void t6040_test_failed_stop_retains_owner(struct kunit *test)
{
	struct t6040_test *ctx = test->priv;

	KUNIT_ASSERT_EQ(test, t6040_test_mux(ctx, TYPEC_DP_STATE_C, true), 0);
	KUNIT_ASSERT_EQ(test, t6040_dp_power_on(&ctx->dp), 0);
	ctx->off_ret = -ETIMEDOUT;
	KUNIT_EXPECT_EQ(test, t6040_dp_power_off(&ctx->dp), -ETIMEDOUT);
	KUNIT_EXPECT_TRUE(test, ctx->tphy.dp_up);
	KUNIT_EXPECT_EQ(test, ctx->sleep_calls, 0U);
	KUNIT_EXPECT_EQ(test, t6040_test_mux(ctx, TYPEC_STATE_USB, false), -ETIMEDOUT);
	ctx->off_ret = 0;
	KUNIT_EXPECT_EQ(test, t6040_dp_power_off(&ctx->dp), 0);
	KUNIT_EXPECT_EQ(test, t6040_test_mux(ctx, TYPEC_STATE_USB, false), 0);
}

static void t6040_test_idempotent_power(struct kunit *test)
{
	struct t6040_test *ctx = test->priv;

	KUNIT_ASSERT_EQ(test, t6040_test_mux(ctx, TYPEC_DP_STATE_C, true), 0);
	KUNIT_EXPECT_EQ(test, t6040_dp_power_on(&ctx->dp), 0);
	KUNIT_EXPECT_EQ(test, t6040_dp_power_on(&ctx->dp), 0);
	KUNIT_EXPECT_EQ(test, ctx->init_calls, 1U);
	KUNIT_EXPECT_EQ(test, t6040_dp_power_off(&ctx->dp), 0);
	KUNIT_EXPECT_EQ(test, t6040_dp_power_off(&ctx->dp), 0);
	KUNIT_EXPECT_EQ(test, ctx->off_calls, 1U);
}

static int t6040_test_seq_step(struct t6040_usb2_phy *tphy, const struct atc_op *op)
{
	struct t6040_test *ctx = container_of(tphy, struct t6040_test, tphy);

	return ++ctx->seq_calls == ctx->fail_at ? -ETIMEDOUT : 0;
}

static void t6040_test_partial_link_is_stopped(struct kunit *test)
{
	struct t6040_test *ctx = test->priv;
	union phy_configure_opts opts = {
		.dp = { .set_rate = 1, .link_rate = 5400, .lanes = 4 },
	};

	KUNIT_ASSERT_EQ(test, t6040_test_mux(ctx, TYPEC_DP_STATE_C, true), 0);
	KUNIT_ASSERT_EQ(test, t6040_dp_power_on(&ctx->dp), 0);
	kunit_deactivate_static_stub(test, t6040_dp_set_rate);
	kunit_activate_static_stub(test, t6040_dp_seq_step, t6040_test_seq_step);
	ctx->fail_at = 1;
	KUNIT_EXPECT_EQ(test, t6040_dp_configure(&ctx->dp, &opts), -ETIMEDOUT);
	KUNIT_EXPECT_EQ(test, ctx->tphy.dp_rate, -1);
	KUNIT_EXPECT_TRUE(test, ctx->tphy.dp_link_dirty);
	/* A partial on must run the off sequence, even without a committed rate. */
	ctx->fail_at = ctx->seq_calls + 1;
	opts.dp.link_rate = 0;
	KUNIT_EXPECT_EQ(test, t6040_dp_configure(&ctx->dp, &opts), -ETIMEDOUT);
	ctx->fail_at = ctx->seq_calls + 1;
	KUNIT_EXPECT_EQ(test, t6040_dp_power_off(&ctx->dp), -ETIMEDOUT);
	KUNIT_EXPECT_TRUE(test, ctx->tphy.dp_up);
	KUNIT_EXPECT_EQ(test, ctx->sleep_calls, 0U);
	ctx->fail_at = 0;
	KUNIT_ASSERT_EQ(test, t6040_dp_power_off(&ctx->dp), 0);
	KUNIT_EXPECT_FALSE(test, ctx->tphy.dp_up);
	KUNIT_EXPECT_FALSE(test, ctx->tphy.dp_link_dirty);
	KUNIT_EXPECT_EQ(test, ctx->sleep_calls, 1U);
}

static struct kunit_case t6040_test_cases[] = {
	KUNIT_CASE(t6040_test_assignments),
	KUNIT_CASE(t6040_test_missing_usb3_is_not_hdmi),
	KUNIT_CASE(t6040_test_requires_assignment),
	KUNIT_CASE(t6040_test_live_usb_is_not_parked),
	KUNIT_CASE(t6040_test_usb_stays_on_dummy),
	KUNIT_CASE(t6040_test_disconnect_drains),
	KUNIT_CASE(t6040_test_usb3_after_dp),
	KUNIT_CASE(t6040_test_hpd_low_keeps_dp_lanes),
	KUNIT_CASE(t6040_test_failed_init),
	KUNIT_CASE(t6040_test_failed_stop_retains_owner),
	KUNIT_CASE(t6040_test_idempotent_power),
	KUNIT_CASE(t6040_test_partial_link_is_stopped),
	{}
};

static struct kunit_suite t6040_test_suite = {
	.name = "apple-t6040-typec",
	.init = t6040_test_init,
	.test_cases = t6040_test_cases,
};

kunit_test_suite(t6040_test_suite);
