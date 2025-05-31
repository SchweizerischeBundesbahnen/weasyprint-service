# Changelog

## [65.1.1](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/compare/v65.1.0...v65.1.1) (2025-05-31)


### Bug Fixes

* support 'ex' units ([#153](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/153)) ([dd96fd4](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/dd96fd4ba9418f5313ea10ca7dfef47d1523d757)), closes [#152](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/152)
* support scaling for retina devices ([#155](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/155)) ([b075537](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/b0755378fac9592089ae6b7c61ad26a68ad63071)), closes [#151](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/151)

## [65.1.0](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/compare/v65.0.1...v65.1.0) (2025-04-25)


### Features

* **deps:** update dependency weasyprint to v65.1 ([#142](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/142)) ([de48bee](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/de48beee44e7e20d709b6231f68050f89b9a1ade))
* use fastapi instead of flask ([#134](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/134)) ([c30471d](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/c30471ddab556cc4f312f5c506d32f528c055dbd))

## [65.0.1](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/compare/v65.0.0...v65.0.1) (2025-04-03)


### Bug Fixes

* revert changes in entrypoint.sh due to DBus Debian config ([#132](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/132)) ([95dd8c3](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/95dd8c30f9107263c9f15da37104b1dc6942af24))

## [65.0.0](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/compare/v63.1.0...v65.0.0) (2025-03-27)


### Features

* **deps:** update dependency weasyprint to v64.1 ([691c97a](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/691c97a06645da42de754cd336d6ddd3032b5b61))
* integrate system tests in weasyprint-service ([#127](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/127)) ([b8554c1](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/b8554c10442b7224655d68c09b282f41702df490))
* set up logging with Docker volumes and configurable log levels … ([#122](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/122)) ([6d30bc6](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/6d30bc6255bdd620249b1bd5ed31cb5772b078d9))
* Swagger UI for Flask REST API ([#126](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/126)) ([2c9882b](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/2c9882bb2257e09da14f3fad813a34d6f5c8ac29))
* switch to new chromium headless mode ([#118](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/118)) ([695ea30](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/695ea30ce1fed0a3717506624d7cf7527ffc60c7))


### Bug Fixes

* alpine dbus problems ([#114](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/114)) ([4ad1872](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/4ad18729ecc17082b8273bfb54c95553b8716830))
* container restart does not work after migration to alpine ([#115](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/115)) ([7763b8b](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/7763b8bb0cc0ea7fbabff31c9d91ca772b27f2e6))
* replace debian base image with alpine one ([#105](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/105)) ([d73f025](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/d73f025350a3b4ebf4775effebfd0168d17c0d37))
* support vw/vh and percents in SVG dimensions ([#119](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/119)) ([fe09f4e](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/fe09f4e3d5dcea7392c3b8197336d3daaa8d9821))


### Miscellaneous Chores

* release 64.1.0 ([b3e38a1](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/b3e38a1ad843969c45a5c0f465953f4e4f3b2330))
* release 64.1.0 ([#112](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/112)) ([691c97a](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/691c97a06645da42de754cd336d6ddd3032b5b61))
* release 65.0.0 ([#129](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/129)) ([9de4b9d](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/9de4b9dc49b5d4ba2ad216522e516107d0dda610))

## [63.1.0](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/compare/v62.4.6...v63.1.0) (2025-01-07)


### Miscellaneous Chores

* release 63.1.0 ([#97](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/97)) ([f201389](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/f2013897cb2bc23625d169d2f78083304f5be19f))

## [62.4.6](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/compare/v62.4.5...v62.4.6) (2024-09-26)


### Bug Fixes

* better handling of SVG dimensions ([#79](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/79)) ([89580f2](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/89580f27fe4c66c55aaf4f38b2ef77254e99fded)), closes [#78](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/78)

## [62.4.5](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/compare/v62.4.4...v62.4.5) (2024-09-24)


### Bug Fixes

* extend version endpoint with build timestamp and chromium version ([#76](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/76)) ([1abd8f9](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/1abd8f9cd7d9ab3ec8611e7d59c36c5f8c647c71)), closes [#74](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/74)

## [62.4.4](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/compare/v62.4.3...v62.4.4) (2024-09-20)


### Bug Fixes

* enable hardware acceleration using env variable ([#68](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/68)) ([58c8198](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/58c8198ba8bf2aea87a4db449789d79302d9f34a)), closes [#62](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/62)
* fixed "Failed to connect to socket /run/dbus/system_bus_socket: No such file or directory" ([#66](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/66)) ([269ee1c](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/269ee1c493426668e2413ccbc603c8d3a02b9144)), closes [#60](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/60)
* refactor to reduce cognitive complexity ([#71](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/71)) ([f4b733d](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/f4b733de50e87f92a0a4bcb65de0b468b33196ec)), closes [#69](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/69)
* refactoring + error handling ([#72](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/72)) ([4c836c4](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/4c836c48f9f79f7c25cc90238f7267f184399cad)), closes [#69](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/69)

## [62.4.3](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/compare/v62.4.2...v62.4.3) (2024-09-12)


### Bug Fixes

* svg images bottom part is missing ([#65](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/65)) ([85b15ef](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/85b15ef3f6af200f2a1bc10bda11acbd0cff88fc)), closes [#63](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/63)
* use extra font for rendering special symbols ([#58](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/58)) ([b2a4126](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/b2a41261dbe1c04fd1d30b112eaa22f68d5d32cc)), closes [#57](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/57)

## [62.4.2](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/compare/v62.4.1...v62.4.2) (2024-09-06)


### Bug Fixes

* chromium gpu usage disabled, proper error result handling when t… ([#54](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/54)) ([f551bd7](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/f551bd739fe427826e70316cbfe5ad101777cd82)), closes [#53](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/53)
* chromium gpu usage disabled, proper error result handling when taking a chromium screenshot ([f551bd7](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/f551bd739fe427826e70316cbfe5ad101777cd82))

## [62.4.1](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/compare/v62.4.0...v62.4.1) (2024-08-20)


### Features

* More information about raised error ([#45](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/45)) ([8aa5e35](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/8aa5e35bfed95a91c0f4f2353283e70d49e9bd53)), closes [#43](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/43)


### Miscellaneous Chores

* release 62.4.1 ([#47](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/47)) ([48bb581](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/48bb5814bee5c1149d5adb4245013eb7ae919423))

## [62.4.0](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/compare/v62.3.2...v62.4.0) (2024-07-31)


### Features

* Added info about the used weasyprint docker-image version ([#40](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/40)) ([ad27a7a](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/ad27a7a17b8c995ba6de824c831a91938830d7ab)), closes [#104](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/104)
* info about the used weasyprint docker-image version ([#41](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/41)) ([b63b7c5](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/b63b7c54b40e9960e8363f351fbd59b344eced20))


### Bug Fixes

* Fixed exception exposure into service response ([#38](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/38)) ([494f811](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/494f8110b5795809cf58befe55e0a998c98268e0)), closes [#1](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/1)

## [62.3.2](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/compare/v62.3.1...v62.3.2) (2024-07-22)


### Bug Fixes

* check for SVG is changed ([#36](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/36)) ([4951a52](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/4951a52c8ba09c9bf6e2f9859010f653f2e16186)), closes [#35](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/35)

## [62.3.1](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/compare/v62.3.0...v62.3.1) (2024-06-22)


### Miscellaneous Chores

* **deps:** update dependency weasyprint to v62.3 ([#32](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/32)) ([94d200c](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/94d200c1d75b480af48148e89de8d0a37943bc16))

## [62.3.0](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/compare/v62.2.0...v62.3.0) (2024-06-18)


### Features

* support of pdf_variant parameter ([#26](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/26)) ([9059188](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/9059188060746c704837c51f775222a7b3a5258e))


### Bug Fixes

* add CODEOWNERS ([#22](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/22)) ([09cad9f](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/09cad9f7abe0c5e81340dc30ccf9d0ce346d8f4a))

## [62.2.0](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/compare/v61.2.0...v62.2.0) (2024-06-11)


### Features

* Return Weasyprint and Python versions in header ([#19](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/19)) ([7a7ef22](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/7a7ef22f850125efea41ec5d3d5e0f44126df16c))


### Miscellaneous Chores

* release 62.2.0 ([#21](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/21)) ([555c0e5](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/555c0e522629ffd01292db4f7d73b8209d93a963))

## 61.2.0 (2024-06-05)


### Features

* Initial contribution of weasyprint service ([#5](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/5)) ([8e8e57f](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/8e8e57fca99f0245bd50783bc57b9e5b0b3b04f1))


### Continuous Integration

* add workflow for release and publishing ([#10](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/issues/10)) ([65d1241](https://github.com/SchweizerischeBundesbahnen/weasyprint-service/commit/65d1241cbd4788cbf5db26337eaab71168896dc6))
