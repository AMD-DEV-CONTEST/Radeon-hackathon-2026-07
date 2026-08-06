package com.indusmind.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.ldap.core.support.LdapContextSource;
import org.springframework.security.ldap.authentication.BindAuthenticator;
import org.springframework.security.ldap.authentication.LdapAuthenticationProvider;
import org.springframework.security.ldap.search.FilterBasedLdapUserSearch;
import org.springframework.security.ldap.userdetails.LdapUserDetailsMapper;

/**
 * SCAFFOLDING - inert by default, and not verified against a real directory
 * server (none is available in the environment this was built in).
 *
 * This class is only instantiated at all when indusmind.ldap.enabled=true
 * (see @ConditionalOnProperty below) - with that property unset or false,
 * as it is by default, Spring never creates these beans and this file has
 * zero effect on the running application. It cannot break the existing
 * local-account + JWT login flow just by being present in the codebase.
 *
 * What this class provides: the two building blocks almost any LDAP
 * integration needs - a context source (how to connect to the directory)
 * and a bind authenticator (how to verify a username/password against it).
 * That's genuinely standard, reusable Spring Security wiring.
 *
 * What this class deliberately does NOT do: hook itself into
 * AuthController.login(). That endpoint is live, tested, load-bearing code
 * that every user depends on - branching it into "try LDAP, fall back to
 * local" is exactly the kind of change that should be tested against a real
 * directory before it ships, not wired in blind. The natural next step,
 * once you have a directory to test against, is to inject
 * LdapAuthenticationProvider into AuthController, attempt LDAP bind first,
 * and on success either issue a JWT directly or auto-provision/sync a local
 * UserAccount row (your call - that's a policy decision, not a technical
 * one, and depends on whether you want LDAP-only, LDAP-with-local-fallback,
 * or something else).
 *
 * Configure via (all in backend/.env or your real environment):
 *   INDUSMIND_LDAP_ENABLED=true
 *   INDUSMIND_LDAP_URL=ldap://your-directory:389
 *   INDUSMIND_LDAP_BASE=dc=example,dc=com
 *   INDUSMIND_LDAP_USER_SEARCH_BASE=ou=people
 *   INDUSMIND_LDAP_USER_SEARCH_FILTER=(uid={0})
 *   INDUSMIND_LDAP_MANAGER_DN=cn=admin,dc=example,dc=com   (optional, for a bind-then-search setup)
 *   INDUSMIND_LDAP_MANAGER_PASSWORD=...                     (optional)
 */
@Configuration
@ConditionalOnProperty(name = "indusmind.ldap.enabled", havingValue = "true")
public class LdapSecurityConfig {

    @Bean
    public LdapContextSource ldapContextSource(
            @Value("${indusmind.ldap.url}") String url,
            @Value("${indusmind.ldap.base}") String base,
            @Value("${indusmind.ldap.manager-dn:}") String managerDn,
            @Value("${indusmind.ldap.manager-password:}") String managerPassword) {
        LdapContextSource source = new LdapContextSource();
        source.setUrl(url);
        source.setBase(base);
        if (!managerDn.isBlank()) {
            source.setUserDn(managerDn);
            source.setPassword(managerPassword);
        }
        source.afterPropertiesSet();
        return source;
    }

    @Bean
    public LdapAuthenticationProvider ldapAuthenticationProvider(
            LdapContextSource contextSource,
            @Value("${indusmind.ldap.user-search-base:}") String userSearchBase,
            @Value("${indusmind.ldap.user-search-filter:(uid={0})}") String userSearchFilter) {
        FilterBasedLdapUserSearch search =
                new FilterBasedLdapUserSearch(userSearchBase, userSearchFilter, contextSource);
        BindAuthenticator authenticator = new BindAuthenticator(contextSource);
        authenticator.setUserSearch(search);
        LdapAuthenticationProvider provider = new LdapAuthenticationProvider(authenticator);
        provider.setUserDetailsContextMapper(new LdapUserDetailsMapper());
        return provider;
    }
}
